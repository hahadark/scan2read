"""Page-at-a-time orchestration, with independently persisted OCR results."""
from dataclasses import asdict, replace
import hashlib
import json
import logging
from pathlib import Path
from collections.abc import Callable
from uuid import uuid4
from contextlib import nullcontext
from scan2read.pdf.prefetch import PagePrefetch

from scan2read.cleanup.text import clean_page
from scan2read.cleanup.headers import repeated_margins
from scan2read.cleanup.parentheses import remove_parenthetical
from scan2read.epub.builder import build_epub
from scan2read.ocr.base import OCREngine
from scan2read.pdf.reader import inspect_pdf
from scan2read.pdf.renderer import render_page
from scan2read.pdf.text_layer import correct_with_ocr, extract_text_layer, find_corrupted_blocks
from scan2read.project.storage import load_raw_ocr, save_raw_ocr

logger = logging.getLogger(__name__)


def fingerprint(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _settings_dict(source: Path, dpi: int, engine_key: str, use_text_layer: bool) -> dict:
    return {"source_sha256": fingerprint(source), "dpi": dpi, "engine": engine_key,
            "schema": 1, "text_layer": "auto" if use_text_layer else "off"}


def _settings_key(source: Path, dpi: int, engine_key: str, use_text_layer: bool) -> str:
    settings = _settings_dict(source, dpi, engine_key, use_text_layer)
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


def _ocr_pages(page_numbers, info, project: Path, generation: Path, engine: OCREngine,
               use_text_layer: bool, dpi: int, prepared):
    """Render/OCR (or reuse cached raw OCR for) each page, in order, and yield it.

    Shared by `convert()`'s full run and `ocr_only()`'s page-range-only run --
    identical caching and logging either way, so a page OCR'd by one caller is
    transparently reused by the other.
    """
    for number in page_numbers:
        raw = generation / "raw_ocr" / f"page_{number:04d}.json"
        if raw.exists():
            page = load_raw_ocr(raw)
            if page.page != number:
                raise ValueError(f"Invalid cached page number: {raw}")
            logger.info("Cached OCR: %s / %s", number, info.page_count)
        else:
            image = project / "pages" / f"page_{number:04d}.png"
            if prepared is not None:
                ready = next(prepared)
                if ready.number != number:
                    raise RuntimeError("Prefetched page order mismatch")
                text_page = ready.text_page
            else:
                text_page = extract_text_layer(info.path, number, dpi) if use_text_layer else None
            if text_page is not None:
                logger.info("Text layer: %s / %s", number, info.page_count)
                if find_corrupted_blocks(text_page):
                    if not image.exists():
                        render_page(info.path, number, image, dpi)
                    text_page = correct_with_ocr(text_page, image, engine)
                page = text_page
            else:
                logger.info("Rendering/OCR: %s / %s", number, info.page_count)
                if not image.exists():
                    render_page(info.path, number, image, dpi)
                page = replace(engine.recognize(image), page=number)
            save_raw_ocr(raw, page)
        yield page


def ocr_only(source: Path, work_dir: Path, engine: OCREngine, engine_key: str,
             page_range: tuple[int, int], dpi: int = 300, use_text_layer: bool = True,
             prefetch: bool = False) -> None:
    """Render/OCR and cache one page range of `source`, without building an EPUB.

    Used to split OCR -- the slow, GPU-bound phase -- across several
    processes covering disjoint page ranges of the same book. Since the
    cache key excludes the page range (see `_settings_key`) and raw OCR is
    stored one independent file per page, this can run concurrently with
    other `ocr_only()`/`convert()` calls on different ranges of the same
    book, writing into the same work-dir project, as long as none of them
    pass `force=True` to `convert()` -- that reassigns the project's
    "generation" to a fresh UUID, which this function does not know about
    (it always targets the "initial" generation, the one every non-forced
    `convert()` call also uses).
    """
    info = inspect_pdf(source)
    start, end = page_range
    if not 1 <= start <= end <= info.page_count:
        raise ValueError(f"Page range must satisfy 1 <= start <= end <= {info.page_count}")
    project = work_dir / _settings_key(source, dpi, engine_key, use_text_layer)
    generation = project / "generations" / "initial"
    page_numbers = range(start, end + 1)
    missing = (n for n in page_numbers if not (generation / "raw_ocr" / f"page_{n:04d}.json").exists())
    preparation = PagePrefetch(info.path, missing, project / "pages", dpi, use_text_layer) if prefetch else nullcontext(None)
    with preparation as prepared:
        for _ in _ocr_pages(page_numbers, info, project, generation, engine, use_text_layer, dpi, prepared):
            pass


def convert(source: Path, output: Path, work_dir: Path, engine: OCREngine,
            engine_key: str, validator: Callable[[Path], object], dpi: int = 300,
            force: bool = False, reconstruct_paragraphs: bool = False,
            spacing: Callable[[str], str] | None = None, use_text_layer: bool = True,
            remove_footnotes: bool = False, page_range: tuple[int, int] | None = None,
            remove_parentheses: bool = False, prefetch: bool = False,
            context_join: Callable[[str, str], bool] | None = None,
            ai_enhancer=None, ai_budget=None) -> Path:
    info = inspect_pdf(source)
    if output.resolve() == source.resolve():
        raise ValueError("Output must not overwrite the source PDF")
    if not 36 <= dpi <= 600:
        raise ValueError("DPI must be between 36 and 600")
    if page_range is not None:
        start, end = page_range
        if not 1 <= start <= end <= info.page_count:
            raise ValueError(f"Page range must satisfy 1 <= start <= end <= {info.page_count}")
        page_numbers = range(start, end + 1)
    else:
        page_numbers = range(1, info.page_count + 1)
    settings = _settings_dict(source, dpi, engine_key, use_text_layer)
    key = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
    project = work_dir / key
    if not project.exists():
        legacy_settings = {name: value for name, value in settings.items() if name != "text_layer"}
        legacy_key = hashlib.sha256(json.dumps(legacy_settings, sort_keys=True).encode()).hexdigest()
        if (work_dir / legacy_key / "project.json").exists():
            logger.warning("Previous cache has no text-layer mode; preserving it and creating a separate cache. "
                           "Pages requiring OCR will be processed again once for this mode.")
    manifest_path = project / "project.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"version": 1, "source": str(info.path), "page_count": info.page_count, **settings, "generation": "initial"}
    if force:
        manifest["generation"] = uuid4().hex
    manifest["status"] = "processing"
    write_json(manifest_path, manifest)
    generation = project / "generations" / manifest["generation"]

    def ocr_pages():
        missing = (n for n in page_numbers if not (generation / "raw_ocr" / f"page_{n:04d}.json").exists())
        preparation = PagePrefetch(info.path, missing, project / "pages", dpi, use_text_layer) if prefetch else nullcontext(None)
        with preparation as prepared:
            yield from _ocr_pages(page_numbers, info, project, generation, engine, use_text_layer, dpi, prepared)

    def paragraphs():
        margins = repeated_margins(ocr_pages())
        if reconstruct_paragraphs:
            from scan2read.cleanup.reconstruction import reconstruct
            from scan2read.cleanup.spacing import correct_spacing
            pages = (load_raw_ocr(generation / "raw_ocr" / f"page_{n:04d}.json")
                     for n in page_numbers)
            reconstructed = reconstruct(pages, margins, remove_footnotes, context_join)
            records = []
            for paragraph in reconstructed:
                before = paragraph.text
                after = correct_spacing(before, spacing) if spacing else before
                records.append({**asdict(paragraph), "text": after, "before_spacing": before})
            if ai_enhancer is not None:
                from scan2read.cleanup.ai_filter import needs_ai_review
                selected = [r for r in records
                            if needs_ai_review(r.get("text", ""), r.get("kind", "body"), ai_enhancer.options)]
                if selected:
                    enhanced = dict(zip((id(r) for r in selected), ai_enhancer.enhance(selected)))
                    records = [enhanced.get(id(r), r) for r in records]
            write_json(generation / "clean" / "document.json", records)
            audit = getattr(context_join, "audit_records", None)
            if audit is not None:
                write_json(generation / "clean" / "ai_context.json", audit)
            if ai_enhancer is not None:
                write_json(generation / "clean" / "ai_enhancements.json", ai_enhancer.audit_records)
            if ai_budget is not None:
                write_json(generation / "clean" / "ai_usage.json", ai_budget.snapshot())
            yield from ((record["text"],record.get("kind","body"),record.get("heading_level",0))
                        for record in records if record["text"])
            return
        for number in page_numbers:
            page = load_raw_ocr(generation / "raw_ocr" / f"page_{number:04d}.json")
            cleaned = clean_page(page, margins.get(number), remove_footnotes)
            if spacing:
                from scan2read.cleanup.spacing import correct_spacing
                before = cleaned.paragraphs
                cleaned = replace(cleaned, paragraphs=tuple(correct_spacing(text, spacing) for text in before))
                record = {**asdict(cleaned), "before_spacing": before}
            else:
                record = asdict(cleaned)
            write_json(generation / "clean" / f"page_{number:04d}.json", record)
            yield from ((text,"body",0) for text in cleaned.paragraphs if text)

    def tts_paragraphs():
        # Apply listening-only transforms after Clean Text has been persisted,
        # identically for page cleanup and reconstructed paragraphs.
        for text,kind,level in paragraphs():
            text = remove_parenthetical(text) if remove_parentheses else text
            if text:
                yield (text,kind,level)

    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_name(output.stem + "." + uuid4().hex + ".pending.epub")
    try:
        build_epub(pending, info.title, tts_paragraphs())
        validator(pending)
        pending.replace(output)
        manifest["status"] = "complete"
        manifest["output"] = str(output.resolve())
        write_json(manifest_path, manifest)
        return output
    finally:
        if ai_budget is not None:
            write_json(generation / "clean" / "ai_usage.json", ai_budget.snapshot())
        pending.unlink(missing_ok=True)
