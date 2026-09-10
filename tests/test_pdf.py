from contextlib import closing
import tempfile
import unittest
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from scan2read.pdf.reader import PDFError, inspect_pdf
from scan2read.pdf.renderer import render_page


class PDFTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "synthetic.pdf"
        with pdfium.PdfDocument.new() as document:
            with closing(document.new_page(72, 144)):
                pass
            document.save(self.source)

    def test_inspection(self):
        info = inspect_pdf(self.source)
        self.assertEqual(info.page_count, 1)
        self.assertEqual(info.title, "synthetic")

    def test_missing_and_invalid_input(self):
        with self.assertRaises(PDFError):
            inspect_pdf(self.root / "missing.pdf")
        bad = self.root / "invalid.pdf"
        bad.write_text("not a PDF")
        with self.assertRaises(PDFError):
            inspect_pdf(bad)

    def test_render_dimensions(self):
        output = render_page(self.source, 1, self.root / "pages" / "1.png", dpi=300)
        with Image.open(output) as image:
            self.assertEqual(image.size, (300, 600))

    def test_invalid_page_and_dpi(self):
        for page, dpi in [(0, 300), (2, 300), (1, 0)]:
            with self.assertRaises(ValueError):
                render_page(self.source, page, self.root / "bad.png", dpi)
