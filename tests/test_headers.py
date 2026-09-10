import unittest
from scan2read.ocr.models import OCRBlock, OCRPage
from scan2read.cleanup.headers import repeated_margins
from scan2read.cleanup.text import clean_page


def page(n, label="반복 표제", y=30, kind="line"):
    return OCRPage(n, 800, 1000, (
        OCRBlock("margin", label, (30 if n%2 else 600,y,760,y+15), .9, 0, kind),
        OCRBlock("title", "반복 표제", (100,100,600,150), .9, 1),
        OCRBlock("body", "반복 표제에 관한 본문입니다.", (100,200,700,220), .9, 2)))


class HeaderTests(unittest.TestCase):
    def test_repeated_headers_preserve_title_body_and_raw(self):
        pages = [page(n) for n in range(1,5)]
        original = [p.to_json() for p in pages]
        removed = repeated_margins(iter(pages))
        for p in pages:
            self.assertEqual(removed[p.page], {"margin"})
            clean = clean_page(p, removed[p.page])
            self.assertEqual(clean.removed_block_ids, ("margin",))
            self.assertIn("반복 표제", clean.paragraphs)
            self.assertIn("반복 표제에 관한 본문입니다.", clean.paragraphs)
        self.assertEqual(original, [p.to_json() for p in pages])

    def test_unique_distant_and_explicit_headings_stay(self):
        self.assertFalse(repeated_margins([page(1),page(2)]))
        self.assertFalse(repeated_margins([page(1),page(20),page(40)]))
        self.assertFalse(repeated_margins([page(n,kind="heading") for n in range(1,5)]))

    def test_repeated_footer(self):
        self.assertEqual(len(repeated_margins([page(n,y=950) for n in range(1,5)])),4)

    def test_header_fused_with_its_own_page_number_is_still_detected(self):
        # A PDF text layer sometimes emits a running header and the page
        # number as one block with no separating space (e.g. "저자 서문9").
        # The header text is constant but the number differs every page, so
        # naive exact-text matching would never see it as "repeated".
        pages = [OCRPage(n, 800, 1000, (
                    OCRBlock("margin", f"저자 서문{n}", (30, 30, 200, 45), .9, 0),
                    OCRBlock("body", "본문 내용입니다.", (100, 200, 700, 220), .9, 1)))
                 for n in range(9, 20)]
        removed = repeated_margins(iter(pages))
        for p in pages:
            self.assertEqual(removed[p.page], {"margin"})
            clean = clean_page(p, removed[p.page])
            self.assertNotIn(f"저자 서문{p.page}", clean.paragraphs)
            self.assertIn("본문 내용입니다.", clean.paragraphs)

    def test_wide_real_book_margins_are_still_caught(self):
        # A real converted book had its header ending at ~13% of page height
        # and its footer starting at ~89% -- both outside the old 7%/93%
        # band, so they were never even considered as margin candidates.
        height = 2584
        pages = [OCRPage(n, 1721, height, (
                    OCRBlock("head", "저자서문", (1249, 284, 1458, 347), .9, 0),
                    OCRBlock("body", "본문 내용입니다.", (250, 1100, 1450, 1160), .9, 1),
                    OCRBlock("foot", f"저자서문{n}", (1309, 2306, 1470, 2350), .9, 2)))
                 for n in range(9, 20)]
        removed = repeated_margins(iter(pages))
        for p in pages:
            self.assertEqual(removed[p.page], {"head", "foot"})

    def test_changing_chapter_title_still_tracked_by_its_page_offset(self):
        # A real book with 32 short chapters: the footer's label is the
        # CURRENT chapter's title, so it changes every few pages and never
        # repeats often enough as literal text. But its embedded number
        # always equals (page - 1), the same offset throughout -- that
        # alone is enough to recognize it as one continuous running footer.
        titles = {9: "일곱 교회", 11: "일곱 교회", 13: "죽도록 충성하라", 15: "죽도록 충성하라"}
        pages = [OCRPage(n, 800, 1000, (
                    OCRBlock("foot", f"{titles.get(n, '책 제목')}{n-1}", (600, 940, 760, 955), .9, 0),
                    OCRBlock("body", "본문 내용입니다.", (100, 200, 700, 220), .9, 1)))
                 for n in range(1, 20)]
        removed = repeated_margins(iter(pages))
        for p in pages:
            self.assertEqual(removed[p.page], {"foot"})

    def test_offset_tracking_does_not_catch_a_one_off_citation_number(self):
        # A single sentence that happens to end in a number (e.g. a Bible
        # reference) must not be mistaken for a page-number-bearing footer
        # just because it sits near the page edge once or twice.
        pages = [OCRPage(n, 800, 1000, (
                    OCRBlock("verse", "그가 이르시되 내가 알파와 오메가라(계22:13)", (100, 940, 700, 985), .9, 0),
                    OCRBlock("body", "본문 내용입니다.", (100, 200, 700, 220), .9, 1)))
                 for n in (5, 6)]
        self.assertFalse(repeated_margins(iter(pages)))

    def test_alternating_recto_verso_headers_with_fused_numbers_stay_distinct(self):
        # Odd pages: "title" + number. Even pages: number + "booktitle".
        # These must form two separate repetition groups, not collide.
        pages = []
        for n in range(9, 20):
            label = f"저자 서문{n}" if n % 2 else f"{n}사무엘 하"
            pages.append(OCRPage(n, 800, 1000, (
                OCRBlock("margin", label, (30, 30, 200, 45), .9, 0),
                OCRBlock("body", "본문 내용입니다.", (100, 200, 700, 220), .9, 1))))
        removed = repeated_margins(iter(pages))
        for p in pages:
            self.assertEqual(removed[p.page], {"margin"})
