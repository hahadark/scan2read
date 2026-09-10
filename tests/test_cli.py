from contextlib import closing, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import pypdfium2 as pdfium

from scan2read.cli import main, parse_page_range


def _fake_kiwipiepy_module():
    """kiwipiepy isn't installed in this dev venv; --reconstruct only needs
    .analyze()/.space() to exist, never their real linguistic output here."""
    module = types.ModuleType("kiwipiepy")
    class FakeKiwi:
        def __init__(self, num_workers=2): pass
        def analyze(self, text, top_n=1): return [([], 0.0)]
        def space(self, text, reset_whitespace=True): return text
    module.Kiwi = FakeKiwi
    return module


class PageRangeParsingTests(unittest.TestCase):
    def test_parses_valid_range(self):
        self.assertEqual(parse_page_range("30-50"), (30, 50))
        self.assertEqual(parse_page_range("1-1"), (1, 1))

    def test_rejects_malformed_and_backwards_ranges(self):
        import argparse
        for value in ("abc", "30", "30-", "-50", "50-30", "0-10"):
            with self.assertRaises(argparse.ArgumentTypeError):
                parse_page_range(value)

    def test_cli_rejects_malformed_pages_argument(self):
        with self.assertRaises(SystemExit):
            main(["convert", "book.pdf", "--pages", "not-a-range"])


class CLITests(unittest.TestCase):
    def test_help(self):
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main([]), 0)
        self.assertIn("scan2read", output.getvalue())

    def test_inspect_reports_page_and_text_layer_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "blank.pdf"
            with pdfium.PdfDocument.new() as document:
                for _ in range(2):
                    with closing(document.new_page(72, 144)):
                        pass
                document.save(source)
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["inspect", str(source)]), 0)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary, {"page_count": 2, "pages_with_text_layer": 0})

    def test_inspect_missing_file_fails_cleanly(self):
        self.assertEqual(main(["inspect", "does-not-exist.pdf"]), 1)

    def test_ai_provider_flag_selects_the_matching_env_var_and_provider_class(self):
        from scan2read.cleanup.ai_providers import AnthropicProvider
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "book.pdf"
            with pdfium.PdfDocument.new() as document:
                with closing(document.new_page(72, 144)):
                    pass
                document.save(source)
            epubcheck = root / "epubcheck.jar"
            epubcheck.write_bytes(b"")
            captured = {}
            def fake_convert(*args, **kwargs):
                captured.update(kwargs)
                return source.with_suffix(".epub")
            with patch("scan2read.pipeline.convert", side_effect=fake_convert), \
                 patch("scan2read.ocr.tesseract.TesseractEngine.cache_identity", return_value="v1"), \
                 patch.dict(sys.modules, {"kiwipiepy": _fake_kiwipiepy_module()}), \
                 patch.dict("os.environ", {"ANTHROPIC_API_KEY": "claude-secret"}, clear=False):
                code = main(["convert", str(source), "--reconstruct", "--ai-anomalies",
                             "--ai-provider", "anthropic", "--ai-model", "claude-sonnet-5",
                             "--epubcheck", str(epubcheck)])
            self.assertEqual(code, 0)
            self.assertIsInstance(captured["ai_enhancer"].provider, AnthropicProvider)
            self.assertEqual(captured["ai_enhancer"].provider.model, "claude-sonnet-5")
            self.assertEqual(captured["ai_budget"].model.provider, "anthropic")

    def test_ai_glosses_flag_enables_the_glosses_option(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "book.pdf"
            with pdfium.PdfDocument.new() as document:
                with closing(document.new_page(72, 144)):
                    pass
                document.save(source)
            epubcheck = root / "epubcheck.jar"
            epubcheck.write_bytes(b"")
            captured = {}
            def fake_convert(*args, **kwargs):
                captured.update(kwargs)
                return source.with_suffix(".epub")
            with patch("scan2read.pipeline.convert", side_effect=fake_convert), \
                 patch("scan2read.ocr.tesseract.TesseractEngine.cache_identity", return_value="v1"), \
                 patch.dict(sys.modules, {"kiwipiepy": _fake_kiwipiepy_module()}), \
                 patch.dict("os.environ", {"OPENAI_API_KEY": "sk-secret"}, clear=False):
                code = main(["convert", str(source), "--reconstruct", "--ai-glosses",
                             "--epubcheck", str(epubcheck)])
            self.assertEqual(code, 0)
            self.assertTrue(captured["ai_enhancer"].options.glosses)

    def test_missing_provider_specific_key_skips_ai_and_still_converts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "book.pdf"
            with pdfium.PdfDocument.new() as document:
                with closing(document.new_page(72, 144)):
                    pass
                document.save(source)
            epubcheck = root / "epubcheck.jar"
            epubcheck.write_bytes(b"")
            captured = {}
            def fake_convert(*args, **kwargs):
                captured.update(kwargs)
                return source.with_suffix(".epub")
            with patch("scan2read.pipeline.convert", side_effect=fake_convert), \
                 patch("scan2read.ocr.tesseract.TesseractEngine.cache_identity", return_value="v1"), \
                 patch.dict(sys.modules, {"kiwipiepy": _fake_kiwipiepy_module()}), \
                 patch.dict("os.environ", {}, clear=True):
                code = main(["convert", str(source), "--reconstruct", "--ai-anomalies",
                             "--ai-provider", "google", "--epubcheck", str(epubcheck)])
            self.assertEqual(code, 0)
            self.assertIsNone(captured["ai_enhancer"])

    def test_gpu_status_reports_detection_and_install_state(self):
        with patch("scan2read.ocr.gpu.detect_nvidia_gpu", return_value="NVIDIA GeForce RTX 3070"), \
             patch("scan2read.ocr.gpu.gpu_paddle_installed", return_value=False):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["gpu-status"]), 0)
        self.assertEqual(json.loads(output.getvalue()), {"gpu_name": "NVIDIA GeForce RTX 3070", "installed": False})

    def test_gpu_install_streams_progress_and_succeeds(self):
        with patch("scan2read.ocr.gpu.install_gpu_support", return_value=iter(["step one\n", "step two\n"])) as install:
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["gpu-install"]), 0)
        self.assertIn("step one", output.getvalue())
        self.assertIn("GPU support installed.", output.getvalue())
        install.assert_called_once()

    def test_gpu_install_failure_is_reported_cleanly(self):
        def failing(*a, **k):
            yield "partial output\n"
            raise RuntimeError("pip failed")
        with patch("scan2read.ocr.gpu.install_gpu_support", side_effect=failing):
            self.assertEqual(main(["gpu-install"]), 1)

    def test_gpu_flag_without_paddle_engine_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "blank.pdf"
            with pdfium.PdfDocument.new() as document:
                with closing(document.new_page(72, 144)):
                    pass
                document.save(source)
            jar = Path(directory) / "epubcheck.jar"
            jar.touch()
            self.assertEqual(main(["convert", str(source), "--gpu", "--epubcheck", str(jar)]), 1)

    def test_gpu_usage_reports_utilization(self):
        with patch("scan2read.ocr.gpu.gpu_utilization",
                   return_value={"utilization_percent": 63, "memory_used_mb": 4200, "memory_total_mb": 8192}):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["gpu-usage"]), 0)
        self.assertEqual(json.loads(output.getvalue()),
                         {"utilization_percent": 63, "memory_used_mb": 4200, "memory_total_mb": 8192})

    def test_gpu_usage_reports_null_when_unavailable(self):
        with patch("scan2read.ocr.gpu.gpu_utilization", return_value=None):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["gpu-usage"]), 0)
        self.assertIsNone(json.loads(output.getvalue()))

    def test_ocr_pages_caches_only_the_requested_range(self):
        from scan2read.ocr.models import OCRBlock, OCRPage
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "book.pdf"
            with pdfium.PdfDocument.new() as document:
                for _ in range(5):
                    with closing(document.new_page(72, 144)):
                        pass
                document.save(source)
            work = root / "work"
            page = OCRPage(1, 300, 600, (OCRBlock("1", "본문입니다.", (10, 200, 250, 220), .9, 0),))
            with patch("scan2read.ocr.tesseract.TesseractEngine.recognize", return_value=page), \
                 patch("scan2read.ocr.tesseract.TesseractEngine.cache_identity", return_value="v1"):
                code = main(["ocr-pages", str(source), "--work-dir", str(work), "--pages", "2-3"])
            self.assertEqual(code, 0)
            raw = sorted(p.name for p in work.rglob("raw_ocr/*.json"))
            self.assertEqual(raw, ["page_0002.json", "page_0003.json"])

    def test_ocr_pages_requires_pages_argument(self):
        with self.assertRaises(SystemExit):
            main(["ocr-pages", "book.pdf"])

    def test_ocr_pages_missing_file_fails_cleanly(self):
        with patch("scan2read.ocr.tesseract.TesseractEngine.cache_identity", return_value="v1"):
            self.assertEqual(main(["ocr-pages", "does-not-exist.pdf", "--pages", "1-1"]), 1)

    def test_ocr_pages_then_convert_reuses_the_cache(self):
        from scan2read.ocr.models import OCRBlock, OCRPage
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "book.pdf"
            with pdfium.PdfDocument.new() as document:
                for _ in range(4):
                    with closing(document.new_page(72, 144)):
                        pass
                document.save(source)
            work = root / "work"
            jar = root / "epubcheck.jar"
            jar.write_bytes(b"")
            page = OCRPage(1, 300, 600, (OCRBlock("1", "본문입니다.", (10, 200, 250, 220), .9, 0),))
            with patch("scan2read.ocr.tesseract.TesseractEngine.recognize", return_value=page) as recognize, \
                 patch("scan2read.ocr.tesseract.TesseractEngine.cache_identity", return_value="v1"), \
                 patch("scan2read.epub.validator.validate_epub"):
                self.assertEqual(main(["ocr-pages", str(source), "--work-dir", str(work), "--pages", "1-2"]), 0)
                self.assertEqual(main(["ocr-pages", str(source), "--work-dir", str(work), "--pages", "3-4"]), 0)
                self.assertEqual(recognize.call_count, 4)
                recognize.reset_mock()
                code = main(["convert", str(source), "--work-dir", str(work), "--epubcheck", str(jar)])
                self.assertEqual(code, 0)
                recognize.assert_not_called()
