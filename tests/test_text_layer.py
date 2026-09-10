from contextlib import closing
from pathlib import Path
import ctypes
import tempfile
import unittest
from zipfile import ZipFile

import pypdfium2 as pdfium
from pypdfium2 import raw as pdfium_c
from PIL import Image

from scan2read.epub.validator import validate_structure
from scan2read.ocr.models import OCRBlock, OCRPage
from scan2read.pdf.text_layer import correct_with_ocr, extract_text_layer, find_corrupted_blocks
from scan2read.pipeline import convert


def _insert_text(document, page, text, x, y, size=24.0):
    """Draw one line of real, extractable text using a standard (non-embedded) font."""
    obj = pdfium_c.FPDFPageObj_NewTextObj(document.raw, b"Helvetica", ctypes.c_float(size))
    encoded = text.encode("utf-16-le")
    buffer = (ctypes.c_ushort * (len(encoded) // 2 + 1))()
    ctypes.memmove(buffer, encoded, len(encoded))
    if not pdfium_c.FPDFText_SetText(obj, buffer):
        raise RuntimeError("FPDFText_SetText failed")
    pdfium_c.FPDFPageObj_Transform(obj, 1, 0, 0, 1, float(x), float(y))
    if not pdfium_c.FPDFPage_InsertObject(page.raw, obj):
        raise RuntimeError("FPDFPage_InsertObject failed")


def make_text_pdf(path: Path, lines: list[str], width=400, height=600) -> None:
    with pdfium.PdfDocument.new() as document:
        page = document.new_page(width, height)
        y = height - 60
        for line in lines:
            _insert_text(document, page, line, 40, y)
            y -= 40
        pdfium_c.FPDFPage_GenerateContent(page.raw)
        page.close()
        document.save(path)


class FakeEngine:
    def __init__(self, text="corrected"):
        self.calls: list[Path] = []
        self.text = text

    def recognize(self, path):
        self.calls.append(Path(path))
        return OCRPage(1, 50, 50, (OCRBlock("c1", self.text, (0, 0, 40, 20), 0.8, 0),))


class TextLayerExtractionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_extracts_real_text_in_reading_order(self):
        source = self.root / "worded.pdf"
        make_text_pdf(source, ["First line of real text", "Second line follows below"])
        page = extract_text_layer(source, 1, dpi=300, min_chars=1)
        self.assertIsNotNone(page)
        self.assertEqual([b.text for b in sorted(page.blocks, key=lambda b: b.reading_order)],
                          ["First line of real text", "Second line follows below"])
        # Top line on the page must land at a smaller pixel y than the one below it.
        top, bottom = sorted(page.blocks, key=lambda b: b.bbox[1])
        self.assertLess(top.bbox[1], bottom.bbox[1])

    def test_blank_page_has_no_text_layer(self):
        source = self.root / "blank.pdf"
        with pdfium.PdfDocument.new() as document:
            with closing(document.new_page(72, 144)):
                pass
            document.save(source)
        self.assertIsNone(extract_text_layer(source, 1))

    def test_sparse_overlay_text_below_threshold_is_not_a_text_layer(self):
        source = self.root / "stamped.pdf"
        make_text_pdf(source, ["12"])
        self.assertIsNone(extract_text_layer(source, 1, min_chars=20))

    def test_invalid_page_number_raises(self):
        source = self.root / "worded.pdf"
        make_text_pdf(source, ["Only page"])
        with self.assertRaises(ValueError):
            extract_text_layer(source, 2)


class CorruptionDetectionTests(unittest.TestCase):
    def _page(self, text: str) -> OCRPage:
        return OCRPage(1, 100, 100, (OCRBlock("b1", text, (0, 0, 50, 20), 1.0, 0),))

    def test_replacement_character_is_corrupted(self):
        page = self._page(chr(0xFFFD) * 3)
        self.assertEqual(len(find_corrupted_blocks(page)), 1)

    def test_private_use_area_is_corrupted(self):
        page = self._page(chr(0xE000) + chr(0xE001))
        self.assertEqual(len(find_corrupted_blocks(page)), 1)

    def test_isolated_hangul_jamo_is_corrupted(self):
        page = self._page(chr(0x3131) + chr(0x3134))
        self.assertEqual(len(find_corrupted_blocks(page)), 1)

    def test_ordinary_korean_and_english_are_not_corrupted(self):
        page = self._page("정상적인 문장입니다 with English too.")
        self.assertEqual(find_corrupted_blocks(page), ())

    def test_unusual_but_valid_word_is_not_flagged(self):
        # A rare or foreign-looking word must never be "corrected" -- only
        # technical encoding artifacts are, per the conservative cleanup rule.
        page = self._page("Xylyl-4-methoxybenzenesulfonate")
        self.assertEqual(find_corrupted_blocks(page), ())


class CorrectionWithOCRTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.image_path = self.root / "page.png"
        Image.new("RGB", (100, 100), "white").save(self.image_path)

    def test_only_corrupted_blocks_are_replaced(self):
        good = OCRBlock("good", "깨끗한 문장", (0, 0, 40, 20), 1.0, 0)
        bad = OCRBlock("bad", chr(0xFFFD) * 2, (10, 30, 60, 50), 1.0, 1)
        page = OCRPage(1, 100, 100, (good, bad))
        engine = FakeEngine(text="복구된 문장")
        corrected = correct_with_ocr(page, self.image_path, engine)
        by_id = {b.id: b for b in corrected.blocks}
        self.assertEqual(by_id["good"].text, "깨끗한 문장")
        self.assertEqual(by_id["bad"].text, "복구된 문장")
        self.assertEqual(len(engine.calls), 1)

    def test_clean_page_never_calls_engine(self):
        page = OCRPage(1, 100, 100, (OCRBlock("good", "깨끗한 문장", (0, 0, 40, 20), 1.0, 0),))
        engine = FakeEngine()
        corrected = correct_with_ocr(page, self.image_path, engine)
        self.assertEqual(corrected, page)
        self.assertEqual(engine.calls, [])


class PipelineTextLayerTests(unittest.TestCase):
    def test_text_layer_pdf_skips_ocr_entirely(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "worded.pdf"
            make_text_pdf(source, ["Text already embedded in the PDF"])
            output = root / "book.epub"
            engine = FakeEngine()
            convert(source, output, root / "work", engine, "fake-v1", validate_structure)
            self.assertEqual(engine.calls, [])
            with ZipFile(output) as archive:
                self.assertIn("Text already embedded in the PDF", archive.read("EPUB/chapter.xhtml").decode())

    def test_text_layer_disabled_falls_back_to_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "worded.pdf"
            make_text_pdf(source, ["Text already embedded in the PDF"])
            output = root / "book.epub"
            engine = FakeEngine(text="테스트 본문입니다.")
            convert(source, output, root / "work", engine, "fake-v1", validate_structure, use_text_layer=False)
            self.assertEqual(len(engine.calls), 1)
