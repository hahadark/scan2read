from pathlib import Path
import tempfile
import unittest
from PIL import Image, ImageDraw
from scan2read.ocr.columns import TwoColumnEngine, gutter, title_bottom
from scan2read.ocr.models import OCRBlock, OCRPage


class RegionEngine:
    def recognize(self, path):
        with Image.open(path) as image:
            return OCRPage(1, *image.size, (OCRBlock("a", path.stem, (1, 1, 10, 10), .9, 0),))


class ColumnTests(unittest.TestCase):
    def test_order_offsets_and_input_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "page.png"
            with Image.new("RGB", (400, 600), "white") as image:
                draw = ImageDraw.Draw(image)
                for box in [(20,10,80,25),(20,150,100,500),(250,150,350,500)]:
                    draw.rectangle(box, fill="black")
                image.save(path)
            before = path.read_bytes()
            page = TwoColumnEngine(RegionEngine()).recognize(path)
            self.assertEqual([b.text for b in page.blocks], ["region-0", "region-1", "region-2"])
            self.assertGreater(page.blocks[2].bbox[0], 200)
            self.assertGreater(page.blocks[1].bbox[1], 100)
            self.assertEqual(len({b.id for b in page.blocks}), 3)
            self.assertEqual(before, path.read_bytes())

    def test_gutter_returns_none_for_a_too_narrow_image(self):
        # width=5 makes the candidate x-range (int(w*.42), int(w*.58)) empty;
        # this must not raise (regression: min() on an empty iterable).
        with Image.new("RGB", (5, 20), "white") as image:
            self.assertIsNone(gutter(image))

    def test_narrow_crop_falls_back_to_a_single_column(self):
        # A tiny single-line crop (e.g. one OCR block re-recognized for text
        # -layer correction) is too narrow to judge a column split at all.
        class TinyRegionEngine:
            def recognize(self, path):
                with Image.open(path) as image:
                    w, h = image.size
                    return OCRPage(1, w, h, (OCRBlock("a", path.stem, (0, 0, w, h), .9, 0),))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "line.png"
            with Image.new("RGB", (5, 20), "white") as image:
                ImageDraw.Draw(image).rectangle((0, 5, 4, 15), fill="black")
                image.save(path)
            page = TwoColumnEngine(TinyRegionEngine()).recognize(path)
            # Only two regions exist (no column split); the title band is
            # blank here, so just the body region produces a block.
            self.assertEqual([b.text for b in page.blocks], ["region-1"])

    def test_title_and_rule(self):
        with Image.new("RGB", (400, 600), "white") as image:
            draw = ImageDraw.Draw(image)
            draw.line((20, 55, 380, 55), fill="black", width=2)
            self.assertEqual(title_bottom(image), 45)
            draw.rectangle((180, 65, 220, 80), fill="black")
            draw.rectangle((30, 120, 150, 140), fill="black")
            self.assertEqual(title_bottom(image), 100)
