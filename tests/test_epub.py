from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
from unittest.mock import patch
import subprocess

from scan2read.epub.builder import build_epub
from scan2read.epub.validator import validate_structure, validate_epub, EPUBValidationError


class EPUBTests(unittest.TestCase):
    def test_semantic_headings_are_added_to_chapter_and_toc(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"heading.epub"
            build_epub(path,"책",[("제1장 시작","heading",2),("본문입니다.","body",0)])
            with ZipFile(path) as archive:
                chapter=archive.read("EPUB/chapter.xhtml").decode()
                nav=archive.read("EPUB/nav.xhtml").decode()
            self.assertIn('<h2 id="heading-0">제1장 시작</h2>',chapter)
            self.assertIn('chapter.xhtml#heading-0',nav)
    def test_packaging_and_escaping(self):
        with tempfile.TemporaryDirectory() as directory:
            path = build_epub(Path(directory) / "book.epub", "제목 & 책", iter(["한국어 <본문>"]))
            validate_structure(path)
            with ZipFile(path) as archive:
                self.assertIn("한국어 &lt;본문&gt;", archive.read("EPUB/chapter.xhtml").decode())
                self.assertIn(b'version="3.0"', archive.read("EPUB/package.opf"))

    def test_control_characters_from_a_garbled_ocr_region_are_stripped(self):
        # XML 1.0 forbids raw control characters outright -- not even a
        # character reference makes them legal -- and html.escape() does not
        # touch them, so an occasional bad OCR character would otherwise
        # make the whole chapter file fail to parse as XML.
        with tempfile.TemporaryDirectory() as directory:
            path = build_epub(Path(directory) / "book.epub", "제목" + chr(0x01),
                              iter(["본문" + chr(0x00) + "입니다" + chr(0x0b) + "."]))
            validate_structure(path)
            with ZipFile(path) as archive:
                text = archive.read("EPUB/chapter.xhtml").decode()
            self.assertIn("본문입니다.", text)
            self.assertNotIn(chr(0x00), text)
            self.assertNotIn(chr(0x0b), text)

    def test_validation_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = build_epub(root / "book.epub", "title", ["text"])
            jar = root / "epubcheck.jar"
            jar.touch()
            with patch("scan2read.epub.validator.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "ERROR", "")):
                with self.assertRaises(EPUBValidationError):
                    validate_epub(path, jar)
