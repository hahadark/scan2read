from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

import pypdfium2 as pdfium

from scan2read.cleanup.footnotes import find_footnote_block_ids
from scan2read.cleanup.reconstruction import reconstruct
from scan2read.cleanup.text import clean_page
from scan2read.epub.validator import validate_structure
from scan2read.ocr.models import OCRBlock, OCRPage
from scan2read.pipeline import convert


def block(id, text, y, height=20, x=100, right=800, kind="line"):
    return OCRBlock(str(id), text, (x, y, right, y + height), 0.95, id, kind)


class FootnoteDetectionTests(unittest.TestCase):
    def test_detached_superscript_removed_only_with_matching_note(self):
        body = [block(i,"본문 문장입니다.",180+i*35,height=25) for i in range(6)]
        body += [block(6,"인용한 본문 문장입니다.",400,height=25,right=700),
                 block(7,"18",400,height=13,x=696,right=710),
                 block(8,"18",500,height=25),block(9,"19",430,height=13,x=696,right=710)]
        notes = [block(10,"18) 참고 설명입니다.",800,height=18)]
        page=OCRPage(1,1000,1000,tuple(body+notes))
        self.assertEqual(find_footnote_block_ids(page),{"7","10"})
        self.assertEqual(find_footnote_block_ids(OCRPage(1,1000,1000,tuple(body))),set())

    def test_superscript_with_realistic_ocr_bbox_noise_is_still_matched(self):
        # Regression from a real book ("고대 근동 문화" p.102): a genuine
        # superscript "98" measured 0.745x its body line's height and 23px
        # left of that line's own right edge -- both narrowly outside the
        # previous 0.7 height-ratio / 0.3 left-margin thresholds, which were
        # only ever tuned against synthetic geometry. Verified against the
        # real cached OCR (2 matches recovered across 116 pages, 0 regressions)
        # before loosening the thresholds.
        body = [block(i,"본문 문장입니다.",180+i*35,height=25) for i in range(6)]
        body += [block(6,"인용한 본문 문장입니다.",400,height=47,right=1397),
                 block(7,"98",402,height=35,x=1374,right=1419)]
        notes = [block(8,"98) 참고 설명입니다.",800,height=18)]
        page=OCRPage(1,2000,1000,tuple(body+notes))
        self.assertEqual(find_footnote_block_ids(page),{"7","8"})

    def test_long_note_starts_mid_page_without_space_after_marker(self):
        body=[block(i, "본문 문장이 계속됩니다.", 180+i*35, height=25) for i in range(7)]
        notes=[block(7+i, "1)공백이 없는 각주" if i==0 else "각주 이어지는 줄", 470+i*23, height=20) for i in range(20)]
        page=OCRPage(1,1000,1000,tuple(body+notes))
        self.assertEqual(find_footnote_block_ids(page),{b.id for b in notes})

    def test_unnumbered_continuation_below_body_is_removed(self):
        body=[block(i,"본문 문장이 이어집니다.",180+i*35,height=25) for i in range(15)]
        notes=[block(15+i,"이전 페이지 각주의 계속되는 문장",780+i*23,height=20) for i in range(7)]
        page=OCRPage(2,1000,1000,tuple(body+notes))
        self.assertEqual(find_footnote_block_ids(page),{b.id for b in notes})

    def test_midpage_heading_and_body_before_notes_are_preserved(self):
        body=[block(i,"본문 문장이 이어집니다.",100+i*35,height=25) for i in range(9)]
        body += [block(9,"2.제목입니다",500,height=25,right=400),block(10,"새 절의 본문입니다.",560,height=25)]
        notes=[block(11+i,"이전 각주가 계속됩니다.",750+i*23,height=20) for i in range(8)]
        page=OCRPage(2,1000,1000,tuple(body+notes))
        self.assertEqual(find_footnote_block_ids(page),{b.id for b in notes})

    def test_centered_imprint_is_not_an_unnumbered_footnote(self):
        blocks=[block(i,"저자와 출판 정보입니다.",200+i*80,height=25,x=300+(i%3)*80,right=800) for i in range(4)]
        blocks += [block(4+i,"저작권 및 판권 안내입니다.",650+i*35,height=20,x=300+(i%3)*80,right=800) for i in range(8)]
        self.assertEqual(find_footnote_block_ids(OCRPage(4,1000,1000,tuple(blocks))),set())

    def test_marker_and_continuation_lines_are_both_removed(self):
        body = [block(0, "본문 첫 줄입니다.", 100), block(1, "본문 두 번째 줄입니다.", 130),
                block(2, "본문 마지막 줄입니다.", 700)]
        footnote = [block(3, "1. 각주 설명이 시작됩니다", 760, height=15),
                    block(4, "이어지는 각주 내용입니다.", 780, height=15)]
        page = OCRPage(1, 1000, 1000, tuple(body + footnote))
        self.assertEqual(find_footnote_block_ids(page), {"3", "4"})

    def test_symbol_marker_is_detected(self):
        page = OCRPage(1, 1000, 1000, (block(0, "본문", 100), block(1, "본문 계속", 130),
                                        block(2, "* 참고 각주 내용", 760, height=15)))
        self.assertEqual(find_footnote_block_ids(page), {"2"})

    def test_numbered_last_line_same_size_as_body_is_not_a_footnote(self):
        # Position and a marker alone are not enough -- without a real size
        # drop from the body text, this is indistinguishable from a numbered
        # list item that simply landed at the bottom of the page. Three body
        # lines are needed so a median body height can actually be trusted.
        page = OCRPage(1, 1000, 1000, (block(0, "본문 첫 줄입니다.", 100), block(1, "본문 두 번째 줄입니다.", 130),
                                        block(2, "본문 세 번째 줄입니다.", 160),
                                        block(3, "3. 목록 항목처럼 보이는 마지막 문장", 750)))
        self.assertEqual(find_footnote_block_ids(page), set())

    def test_body_text_without_marker_is_untouched(self):
        page = OCRPage(1, 1000, 1000, (block(0, "본문", 100), block(1, "본문 계속되는 마지막 줄", 760)))
        self.assertEqual(find_footnote_block_ids(page), set())

    def test_no_bottom_zone_content_returns_empty(self):
        page = OCRPage(1, 1000, 1000, (block(0, "본문", 100), block(1, "본문 계속", 130)))
        self.assertEqual(find_footnote_block_ids(page), set())


class FootnoteCleanupIntegrationTests(unittest.TestCase):
    def test_clean_page_drops_footnote_only_when_enabled(self):
        page = OCRPage(1, 1000, 1000, (block(0, "본문입니다.", 100),
                                        block(1, "1. 각주 설명입니다", 760, height=15)))
        self.assertIn("1. 각주 설명입니다", clean_page(page).paragraphs)
        cleaned = clean_page(page, remove_footnotes=True)
        self.assertNotIn("1. 각주 설명입니다", cleaned.paragraphs)
        self.assertIn("1", cleaned.removed_block_ids)

    def test_reconstruct_drops_footnote_only_when_enabled(self):
        page = OCRPage(1, 1000, 1000, (block(0, "본문입니다.", 100),
                                        block(1, "1. 각주 설명입니다", 760, height=15)))
        with_footnote = [p.text for p in reconstruct([page], {})]
        without_footnote = [p.text for p in reconstruct([page], {}, remove_footnotes=True)]
        self.assertIn("1. 각주 설명입니다", with_footnote)
        self.assertNotIn("1. 각주 설명입니다", without_footnote)


class FakeEngineWithFootnote:
    def recognize(self, path):
        return OCRPage(1, 1000, 1000, (block(0, "본문입니다.", 100),
                                        block(1, "1. 각주 설명입니다", 760, height=15)))


class PipelineFootnoteTests(unittest.TestCase):
    def _make_source(self, root: Path) -> Path:
        source = root / "input.pdf"
        with pdfium.PdfDocument.new() as document:
            with closing(document.new_page(72, 144)):
                pass
            document.save(source)
        return source

    def test_footnotes_kept_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "book.epub"
            convert(self._make_source(root), output, root / "work", FakeEngineWithFootnote(), "v1", validate_structure)
            with ZipFile(output) as archive:
                self.assertIn("각주 설명입니다", archive.read("EPUB/chapter.xhtml").decode())

    def test_footnotes_removed_when_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "book.epub"
            convert(self._make_source(root), output, root / "work", FakeEngineWithFootnote(), "v1", validate_structure,
                    remove_footnotes=True)
            with ZipFile(output) as archive:
                text = archive.read("EPUB/chapter.xhtml").decode()
                self.assertIn("본문입니다", text)
                self.assertNotIn("각주 설명입니다", text)
