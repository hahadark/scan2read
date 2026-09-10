"""Opt-in integration test requiring local Tesseract, EPUBCheck and Korean font."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from PIL import Image, ImageDraw, ImageFont


@unittest.skipUnless(all(os.environ.get(k) for k in ("SCAN2READ_TESSERACT", "EPUBCHECK_JAR", "SCAN2READ_TEST_FONT")), "Set local OCR, EPUBCheck and Korean font paths")
class RealConversionTests(unittest.TestCase):
    def test_korean_scanned_pdf_and_cached_rerun(self):
        lines = ["책을 듣는 시간", "오늘은 조용한 길을 따라 천천히 걸었습니다.",
                 "나무 사이로 시원한 바람이 불어왔습니다.",
                 "이 문서는 한국어 문자 인식을 확인하는 예제입니다."]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "korean.pdf"
            font = ImageFont.truetype(os.environ["SCAN2READ_TEST_FONT"], 40)
            with Image.new("RGB", (1654, 2339), "white") as image:
                draw = ImageDraw.Draw(image)
                for index, line in enumerate(lines):
                    draw.text((160, 260 + 75 * index), line, font=font, fill="black")
                draw.text((800, 2220), "1", font=font, fill="black")
                image.save(source, resolution=200)
            output = root / "book.epub"
            command = [sys.executable, "-m", "scan2read", "convert", str(source),
                       "--output", str(output), "--work-dir", str(root / "work"),
                       "--tesseract", os.environ["SCAN2READ_TESSERACT"],
                       "--epubcheck", os.environ["EPUBCHECK_JAR"]]
            for iteration in range(2):
                result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
                self.assertEqual(result.returncode, 0, result.stderr)
                if iteration:
                    self.assertIn("Cached OCR: 1 / 1", result.stderr)
                with ZipFile(output) as archive:
                    chapter = ET.fromstring(archive.read("EPUB/chapter.xhtml"))
                    paragraphs = [p.text for p in chapter.findall(".//{http://www.w3.org/1999/xhtml}p")]
                self.assertEqual(" ".join(paragraphs), " ".join(lines))
