"""Command-line entry point."""

import argparse
import json
import logging
import os
from pathlib import Path
import re

from scan2read import __version__


def parse_page_range(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)-(\d+)", value)
    if not match:
        raise argparse.ArgumentTypeError("Page range must look like START-END, e.g. 30-50")
    start, end = int(match.group(1)), int(match.group(2))
    if start < 1 or end < start:
        raise argparse.ArgumentTypeError("Page range must have START >= 1 and END >= START")
    return (start, end)


def _add_engine_arguments(parser: argparse.ArgumentParser) -> None:
    """Shared by `convert` and `ocr-pages`: everything needed to pick and
    configure an OCR engine, nothing about what to do with its output."""
    parser.add_argument("--engine", choices=("tesseract", "paddle"), default="tesseract")
    parser.add_argument("--gpu", action="store_true",
                        help="Use NVIDIA GPU acceleration for --engine paddle (requires 'scan2read gpu-install' first)")
    parser.add_argument("--tesseract", default="tesseract")
    parser.add_argument("--language", default="kor+eng")
    parser.add_argument("--psm", type=int, choices=(3, 4, 6), default=6)
    parser.add_argument("--columns", type=int, choices=(1, 2), default=1,
                        help="Opt-in centered two-column OCR; uses PSM 6 per region")


def _build_engine(args: argparse.Namespace):
    """Construct the OCR engine `convert`/`ocr-pages` both need from the
    arguments `_add_engine_arguments` adds. Returns (engine, cache_identity)."""
    if args.gpu and args.engine != "paddle":
        raise ValueError("--gpu requires --engine paddle")
    if args.engine == "paddle":
        from scan2read.ocr.paddle import PaddleEngine
        engine = PaddleEngine(device="gpu:0" if args.gpu else "cpu")
        identity = engine.cache_identity()
    else:
        from scan2read.ocr.tesseract import TesseractEngine
        engine = TesseractEngine(args.tesseract, args.language, psm=6 if args.columns == 2 else args.psm)
        identity = engine.cache_identity()
    if args.columns == 2:
        from scan2read.ocr.columns import TwoColumnEngine
        engine = TwoColumnEngine(engine)
        identity += ":two-columns-v2"
    return engine, identity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scan2read")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--debug", action="store_true")
    commands = parser.add_subparsers(dest="command")
    conversion = commands.add_parser("convert", help="Convert a scanned PDF into validated EPUB3")
    conversion.add_argument("file", type=Path)
    conversion.add_argument("--output", type=Path)
    conversion.add_argument("--work-dir", type=Path, default=Path("work"))
    conversion.add_argument("--dpi", type=int, default=300)
    conversion.add_argument("--force", action="store_true")
    _add_engine_arguments(conversion)
    conversion.add_argument("--reconstruct", action="store_true", help="Reconstruct paragraphs and cross-page continuations")
    conversion.add_argument("--ai-context", action="store_true",
                            help="Use the configured AI provider for ambiguous paragraph boundaries; falls back locally")
    conversion.add_argument("--ai-ocr-words", action="store_true", help="AI-check suspicious OCR words")
    conversion.add_argument("--ai-spacing", action="store_true", help="AI-check Korean spacing")
    conversion.add_argument("--ai-anomalies", action="store_true", help="AI-report anomalous characters and words")
    conversion.add_argument("--ai-structure", action="store_true", help="AI-classify body, heading, and footnote blocks")
    conversion.add_argument("--ai-headings", action="store_true", help="AI-detect chapter headings for the EPUB TOC")
    conversion.add_argument("--ai-glosses", action="store_true",
                            help="AI-remove redundant parenthetical transliteration glosses (e.g. '(체다카)' after '정의')")
    conversion.add_argument("--ai-provider", choices=("openai", "anthropic", "google"), default="openai",
                            help="AI provider for --ai-* cleanup features")
    conversion.add_argument("--ai-model", default=None,
                            help="Model ID for --ai-provider (default: that provider's low-cost model)")
    conversion.add_argument("--ai-cost-limit-usd", type=float, default=None,
                            help="Maximum AI API cost for this book in USD; switches to local processing at the limit")
    conversion.add_argument("--text-layer", choices=("auto", "off"), default="auto",
                            help="Reuse a page's own embedded PDF text instead of OCR when present (default: auto)")
    conversion.add_argument("--remove-footnotes", action="store_true",
                            help="Drop page-bottom footnotes (opt-in; conservative heuristic, may miss or over-remove some)")
    conversion.add_argument("--remove-parentheses", action="store_true",
                            help="Drop parenthetical asides such as scripture citations, e.g. '(계2:5)' (TTS-only; skipped when a paragraph's parentheses are unbalanced)")
    conversion.add_argument("--spacing", action="store_true", help="Apply optional local Kiwi spacing")
    conversion.add_argument("--pages", type=parse_page_range, default=None,
                            help="Only process this page range, e.g. 30-50 (1-based, inclusive)")
    conversion.add_argument("--epubcheck", type=Path, default=os.environ.get("EPUBCHECK_JAR"))
    inspection = commands.add_parser("inspect", help="Report how many pages already have a usable PDF text layer")
    inspection.add_argument("file", type=Path)
    inspection.add_argument("--dpi", type=int, default=300)
    ocr_pages_cmd = commands.add_parser("ocr-pages",
        help="OCR and cache one page range without building an EPUB (used internally for parallel OCR)")
    ocr_pages_cmd.add_argument("file", type=Path)
    ocr_pages_cmd.add_argument("--work-dir", type=Path, default=Path("work"))
    ocr_pages_cmd.add_argument("--dpi", type=int, default=300)
    _add_engine_arguments(ocr_pages_cmd)
    ocr_pages_cmd.add_argument("--text-layer", choices=("auto", "off"), default="auto",
                               help="Reuse a page's own embedded PDF text instead of OCR when present (default: auto)")
    ocr_pages_cmd.add_argument("--pages", type=parse_page_range, required=True,
                               help="Page range to OCR, e.g. 30-50 (1-based, inclusive)")
    gpu_status = commands.add_parser("gpu-status", help="Report NVIDIA GPU presence and paddlepaddle-gpu install state")
    gpu_usage = commands.add_parser("gpu-usage", help="Report current NVIDIA GPU utilization and VRAM usage")
    gpu_install = commands.add_parser("gpu-install", help="Install the CUDA build of paddlepaddle for GPU-accelerated OCR")
    gpu_install.add_argument("--version", dest="gpu_version", default=None)
    gpu_install.add_argument("--index-url", default=None)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(levelname)s: %(message)s")
    if args.command == "inspect":
        from scan2read.pdf.text_layer import analyze_text_layer
        try:
            summary = analyze_text_layer(args.file, args.dpi)
        except (ValueError, RuntimeError, OSError) as exc:
            logging.error("%s", exc, exc_info=args.debug)
            return 1
        print(json.dumps({"page_count": summary.page_count,
                          "pages_with_text_layer": summary.pages_with_text_layer}))
        return 0
    if args.command == "ocr-pages":
        from scan2read.pipeline import ocr_only
        try:
            engine, identity = _build_engine(args)
            ocr_only(args.file, args.work_dir, engine, identity, args.pages,
                     args.dpi, args.text_layer == "auto", prefetch=args.gpu)
        except (ValueError, RuntimeError, OSError, ImportError) as exc:
            logging.error("%s", exc, exc_info=args.debug)
            return 1
        return 0
    if args.command == "gpu-status":
        from scan2read.ocr.gpu import detect_nvidia_gpu, gpu_paddle_installed
        print(json.dumps({"gpu_name": detect_nvidia_gpu(), "installed": gpu_paddle_installed()}))
        return 0
    if args.command == "gpu-usage":
        from scan2read.ocr.gpu import gpu_utilization
        print(json.dumps(gpu_utilization()))
        return 0
    if args.command == "gpu-install":
        from scan2read.ocr.gpu import DEFAULT_GPU_VERSION, DEFAULT_INDEX_URL, install_gpu_support
        try:
            for line in install_gpu_support(args.gpu_version or DEFAULT_GPU_VERSION, args.index_url or DEFAULT_INDEX_URL):
                print(line, end="", flush=True)
        except RuntimeError as exc:
            logging.error("%s", exc, exc_info=args.debug)
            return 1
        print("GPU support installed.")
        return 0
    from scan2read.epub.validator import validate_epub
    from scan2read.pipeline import convert
    try:
        if args.epubcheck is None or not args.epubcheck.is_file():
            raise ValueError("Set --epubcheck PATH or EPUBCHECK_JAR to an installed EPUBCheck JAR")
        ai_features=(args.ai_context,args.ai_ocr_words,args.ai_spacing,args.ai_anomalies,
                     args.ai_structure,args.ai_headings,args.ai_glosses)
        if any(ai_features) and not args.reconstruct:
            raise ValueError("AI cleanup options require --reconstruct")
        if args.ai_cost_limit_usd is not None and args.ai_cost_limit_usd < 0:
            raise ValueError("--ai-cost-limit-usd must be zero or greater")
        output = args.output or args.file.with_suffix(".epub")
        engine, identity = _build_engine(args)
        spacing = None
        context_join = None
        ai_enhancer = None
        ai_budget = None
        if args.spacing or args.reconstruct:
            from kiwipiepy import Kiwi
            kiwi = Kiwi(num_workers=2)
            if args.spacing:
                spacing = lambda text: kiwi.space(text, reset_whitespace=True)
            if args.reconstruct:
                from scan2read.cleanup.context import ContextJoiner
                context_join = ContextJoiner(kiwi.analyze)
                env_var = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
                          "google": "GOOGLE_API_KEY"}[args.ai_provider]
                api_key = os.environ.get(env_var, "").strip()
                if any(ai_features) and api_key:
                    from scan2read.cleanup.ai_providers import build_provider, default_model, resolve_model
                    from scan2read.cleanup.ai_usage import AICostBudget
                    ai_model = args.ai_model or default_model(args.ai_provider)
                    if ai_model is None:
                        raise ValueError(f"--ai-model is required for --ai-provider {args.ai_provider}")
                    provider = build_provider(args.ai_provider, ai_model, api_key)
                    def report_usage(snapshot):
                        print("SCAN2READ_AI_USAGE " + json.dumps(snapshot, ensure_ascii=False), flush=True)
                    def report_progress(snapshot):
                        print("SCAN2READ_AI_PROGRESS " + json.dumps(snapshot, ensure_ascii=False), flush=True)
                    ai_budget = AICostBudget(args.ai_cost_limit_usd, report_usage,
                                              model=resolve_model(args.ai_provider, ai_model))
                if args.ai_context:
                    if api_key:
                        from scan2read.cleanup.ai_context import AIContextJoiner
                        context_join = AIContextJoiner(provider, context_join, budget=ai_budget,
                                                        progress=report_progress)
                    else:
                        logging.warning("%s is missing; using local context correction", env_var)
                if any(ai_features[1:]):
                    if api_key:
                        from scan2read.cleanup.ai_cache import AIResultCache
                        from scan2read.cleanup.ai_enhance import AIOptions, AIEnhancer
                        ai_enhancer=AIEnhancer(provider,AIOptions(
                            args.ai_ocr_words,args.ai_spacing,args.ai_anomalies,
                            args.ai_structure,args.ai_headings,args.ai_glosses),budget=ai_budget,
                            cache=AIResultCache(args.work_dir/"_ai_cache"),progress=report_progress)
                    else:logging.warning("%s is missing; skipping optional AI cleanup", env_var)
        convert(args.file, output, args.work_dir, engine,
                identity,
                lambda path: validate_epub(path, args.epubcheck), args.dpi, args.force,
                args.reconstruct, spacing, args.text_layer == "auto", args.remove_footnotes, args.pages,
                args.remove_parentheses, prefetch=args.gpu, context_join=context_join,
                ai_enhancer=ai_enhancer, ai_budget=ai_budget)
        if ai_budget is not None:
            report_usage(ai_budget.snapshot())

        print(f"Created: {output}")
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        logging.error("%s", exc, exc_info=args.debug)
        return 1
    except KeyboardInterrupt:
        logging.warning("Interrupted. Run the same command to resume cached pages.")
        return 130
    return 0
