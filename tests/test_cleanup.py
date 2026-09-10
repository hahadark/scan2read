import unittest

from scan2read.cleanup.text import clean_page
from scan2read.ocr.models import OCRBlock, OCRPage


def line(id, text, y, x=100, kind="line"):
    return OCRBlock(str(id), text, (x, y, 800, y + 20), .95, id, kind)


class CleanupTests(unittest.TestCase):
    def test_margin_numbers_only(self):
        page = OCRPage(1, 1000, 1000, (line(0, "12", 10), line(1, "2024", 200), line(2, "- 13 -", 950)))
        original = page.to_json()
        clean = clean_page(page)
        self.assertEqual(clean.paragraphs, ("2024",))
        self.assertEqual(clean.removed_block_ids, ("0", "2"))
        self.assertEqual(page.to_json(), original)

    def test_join_and_paragraph_gap(self):
        page = OCRPage(1, 1000, 1000, (line(0, "첫 문장의", 200), line(1, "이어지는 부분입니다.", 225), line(2, "새 문단입니다.", 290)))
        self.assertEqual(clean_page(page).paragraphs, ("첫 문장의 이어지는 부분입니다.", "새 문단입니다."))

    def test_heading_and_indentation(self):
        page = OCRPage(1, 1000, 1000, (line(0, "제1장", 100, kind="heading"), line(1, "본문", 125), line(2, "다음 문단", 150, x=140)))
        self.assertEqual(clean_page(page).paragraphs, ("제1장", "본문", "다음 문단"))

    def test_blank_page(self):
        self.assertEqual(clean_page(OCRPage(1, 100, 100, ())).paragraphs, ())

    def test_bare_page_number_wider_than_the_old_8_92_percent_band(self):
        # A real book's bare page-number footer measured at 90.9% down the
        # page -- past the old fixed 92% cutoff, so it leaked into the text.
        page = OCRPage(1, 1000, 1000, (line(0, "본문입니다.", 500), line(1, "77", 910)))
        clean = clean_page(page)
        self.assertEqual(clean.paragraphs, ("본문입니다.",))
        self.assertIn("1", clean.removed_block_ids)

    def test_isolated_stray_mark_between_real_paragraphs_is_dropped(self):
        # Real book ("기독교 위험한 사상 1", p.101): a decorative section
        # divider misread by OCR as a bare ";" survived as its own paragraph,
        # mid-sentence, with nothing to merge it into either neighbor.
        page = OCRPage(1, 1000, 1000, (
            line(0, "본문 문장입니다.", 200),
            OCRBlock("1", ";", (400, 400, 412, 415), .9, 1, "line"),
            line(2, "다음 문단입니다.", 600),
        ))
        clean = clean_page(page)
        self.assertEqual(clean.paragraphs, ("본문 문장입니다.", "다음 문단입니다."))
        self.assertIn("1", clean.removed_block_ids)

    def test_isolated_dust_speck_flagged_by_size_not_content(self):
        # Real book ("고대 근동 문화", p.113): a 10x10px detector blob,
        # physically far smaller than any real glyph, misread as digit "8".
        # Digits are never dropped for content (a real page number/heading
        # numeral must survive), only when their own box is implausibly tiny.
        page = OCRPage(1, 1000, 1000, (
            line(0, "본문 문장입니다.", 200),
            OCRBlock("1", "8", (500, 250, 504, 254), .9, 1, "line"),
            line(2, "다음 문단입니다.", 600),
        ))
        clean = clean_page(page)
        self.assertEqual(clean.paragraphs, ("본문 문장입니다.", "다음 문단입니다."))
        self.assertIn("1", clean.removed_block_ids)

    def test_isolated_short_heading_with_hangul_or_roman_numeral_is_kept(self):
        # A real, normal-sized standalone heading must never be mistaken for
        # noise just because it is short.
        page = OCRPage(1, 1000, 1000, (
            line(0, "본문 문장입니다.", 200),
            line(1, "3장", 400),
            OCRBlock("2", "IV", (100, 600, 300, 640), .9, 2, "line"),
            line(3, "다음 문단입니다.", 800),
        ))
        clean = clean_page(page)
        self.assertEqual(clean.paragraphs, ("본문 문장입니다.", "3장", "IV", "다음 문단입니다."))
        self.assertEqual(clean.removed_block_ids, ())
