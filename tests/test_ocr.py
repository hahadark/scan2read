from pathlib import Path
import tempfile
import unittest
import subprocess
from unittest.mock import patch

from scan2read.ocr.base import OCRError
from scan2read.ocr.models import OCRBlock, OCRPage
from scan2read.ocr.tesseract import TesseractEngine, parse_tsv, apply_native_spacing
from scan2read.project.storage import load_raw_ocr, save_raw_ocr


class OCRTests(unittest.TestCase):
    def test_model_update_invalidates_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "tesseract"
            binary.write_bytes(b"executable")
            model = root / "kor.traineddata"
            model.write_bytes(b"model-v1")
            result = subprocess.CompletedProcess([], 0, f'List of available languages in "{root}" (1):\nkor\n', "")
            with patch("scan2read.ocr.tesseract.shutil.which", return_value=str(binary)), patch("scan2read.ocr.tesseract.subprocess.run", return_value=result):
                engine = TesseractEngine(language="kor")
                initial = engine.cache_identity()
                model.write_bytes(b"model-v2")
                self.assertNotEqual(initial, engine.cache_identity())

    def test_native_korean_spacing_and_mismatch(self):
        page = OCRPage(1, 100, 200, (OCRBlock("a", "오 늘 은 좋은 날", (1, 1, 99, 20), .9, 0),))
        self.assertEqual(apply_native_spacing(page, "오늘은 좋은 날\n").blocks[0].text, "오늘은 좋은 날")
        self.assertEqual(page.blocks[0].text, "오 늘 은 좋은 날")
        for text in ("오늘은 다른 날", "오늘은\n좋은 날"):
            with self.assertRaises(OCRError):
                apply_native_spacing(page, text)

    def setUp(self):
        self.page = OCRPage(2, 100, 200, (OCRBlock("a", "한국어 원문", (5, 10, 90, 30), .9, 0),))

    def test_roundtrip(self):
        self.assertEqual(OCRPage.from_json(self.page.to_json()), self.page)
        self.assertIn("한국어", self.page.to_json())

    def test_invalid_geometry(self):
        with self.assertRaises(ValueError):
            OCRPage(1, 10, 10, self.page.blocks)
        with self.assertRaises(ValueError):
            OCRBlock("a", "x", (1, 1, 3, 3), float("nan"), 0)

    def test_immutable_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw_ocr" / "page_0002.json"
            save_raw_ocr(path, self.page)
            original = path.read_bytes()
            self.assertEqual(load_raw_ocr(path), self.page)
            with self.assertRaises(FileExistsError):
                save_raw_ocr(path, OCRPage(2, 100, 200, ()))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(len(list(path.parent.iterdir())), 1)

    def test_tsv_line_grouping(self):
        tsv = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        tsv += "5\t1\t1\t1\t1\t1\t10\t20\t30\t10\t90\t한국어\n"
        tsv += "5\t1\t1\t1\t1\t2\t45\t20\t20\t10\t80\t문장\n"
        tsv += "5\t1\t1\t1\t2\t1\t10\t40\t30\t10\t95\t다음\n"
        page = parse_tsv(tsv, 100, 200)
        self.assertEqual(len(page.blocks), 2)
        self.assertEqual(page.blocks[0].text, "한국어 문장")
        self.assertEqual(page.blocks[0].bbox, (10, 20, 65, 30))
        self.assertAlmostEqual(page.blocks[0].confidence, .85)

    def test_missing_engine(self):
        with patch("scan2read.ocr.tesseract.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(OCRError, "not installed"):
                TesseractEngine().recognize(Path("page.png"))
