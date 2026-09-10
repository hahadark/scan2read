from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

import pypdfium2 as pdfium

from scan2read.epub.validator import validate_structure
from scan2read.ocr.models import OCRBlock, OCRPage
from scan2read.pipeline import convert


class NumberedEngine:
    def __init__(self):
        self.calls = []

    def recognize(self, path):
        number = int(Path(path).stem.split("_")[1])
        self.calls.append(number)
        return OCRPage(number, 300, 600, (
            OCRBlock(str(number), f"페이지 {number} 본문입니다.",
                     (10, 200, 250, 220), .9, 0),))


def source_pdf(path: Path, pages: int = 3):
    with pdfium.PdfDocument.new() as document:
        for _ in range(pages):
            with closing(document.new_page(72, 144)):
                pass
        document.save(path)


class PrefetchTests(unittest.TestCase):
    def test_prefetch_matches_sequential_output_and_raw_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.pdf"
            source_pdf(source)
            sequential = root / "sequential.epub"
            prefetched = root / "prefetched.epub"
            convert(source, sequential, root / "work-sequential", NumberedEngine(),
                    "test", validate_structure, use_text_layer=False)
            engine = NumberedEngine()
            convert(source, prefetched, root / "work-prefetch", engine,
                    "test", validate_structure, use_text_layer=False, prefetch=True)
            self.assertEqual(engine.calls, [1, 2, 3])
            with ZipFile(sequential) as first, ZipFile(prefetched) as second:
                self.assertEqual(first.read("EPUB/chapter.xhtml"),
                                 second.read("EPUB/chapter.xhtml"))
            first_raw = [p.read_bytes() for p in sorted((root / "work-sequential").rglob("raw_ocr/*.json"))]
            second_raw = [p.read_bytes() for p in sorted((root / "work-prefetch").rglob("raw_ocr/*.json"))]
            self.assertEqual(first_raw, second_raw)

    def test_prefetch_skips_cached_pages_and_resumes_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.pdf"
            source_pdf(source)
            engine = NumberedEngine()
            convert(source, root / "first.epub", root / "work", engine,
                    "test", validate_structure, use_text_layer=False,
                    page_range=(1, 1), prefetch=True)
            self.assertEqual(engine.calls, [1])
            convert(source, root / "all.epub", root / "work", engine,
                    "test", validate_structure, use_text_layer=False,
                    prefetch=True)
            self.assertEqual(engine.calls, [1, 2, 3])
            convert(source, root / "cached.epub", root / "work", engine,
                    "test", validate_structure, use_text_layer=False,
                    prefetch=True)
            self.assertEqual(engine.calls, [1, 2, 3])

