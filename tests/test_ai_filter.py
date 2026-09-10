import unittest

from scan2read.cleanup.ai_enhance import AIOptions
from scan2read.cleanup.ai_filter import needs_ai_review


class AIFilterTests(unittest.TestCase):
    def test_no_active_feature_never_sends_anything(self):
        self.assertFalse(needs_ai_review("아무 문제 없는 평범한 문장입니다.", "body", AIOptions()))

    def test_empty_or_blank_text_is_never_sent(self):
        options = AIOptions(True, True, True, True, True)
        self.assertFalse(needs_ai_review("", "body", options))
        self.assertFalse(needs_ai_review("   ", "body", options))

    def test_ordinary_well_formed_paragraph_is_skipped_for_every_feature(self):
        text = "이것은 평범하게 띄어쓰기가 되어 있고 마침표로 끝나는 본문 문장입니다."
        self.assertFalse(needs_ai_review(text, "body", AIOptions(ocr_words=True)))
        self.assertFalse(needs_ai_review(text, "body", AIOptions(spacing=True)))
        self.assertFalse(needs_ai_review(text, "body", AIOptions(anomalies=True)))
        self.assertFalse(needs_ai_review(text, "body", AIOptions(structure=True)))

    def test_mixed_script_glitch_triggers_ocr_words(self):
        self.assertTrue(needs_ai_review("안g녕하세요 반갑습니다.", "body", AIOptions(ocr_words=True)))
        self.assertFalse(needs_ai_review("안g녕하세요 반갑습니다.", "body", AIOptions(spacing=True)))

    def test_repeated_glyph_triggers_ocr_words(self):
        self.assertTrue(needs_ai_review("ㅁㅁㅁㅁ 잡음이 섞였다.", "body", AIOptions(ocr_words=True)))

    def test_corruption_marker_triggers_anomalies_only(self):
        text = "본문 중간에 � 문자가 있다."
        self.assertTrue(needs_ai_review(text, "body", AIOptions(anomalies=True)))
        self.assertFalse(needs_ai_review(text, "body", AIOptions(ocr_words=True)))

    def test_long_unspaced_hangul_run_triggers_spacing(self):
        text = "가나다라마바사아자차카타파하가나다라 그리고 나머지 문장."
        self.assertTrue(needs_ai_review(text, "body", AIOptions(spacing=True)))

    def test_short_non_terminal_body_line_is_a_heading_candidate(self):
        self.assertTrue(needs_ai_review("제3장 새로운 시작", "body", AIOptions(structure=True)))
        self.assertTrue(needs_ai_review("제3장 새로운 시작", "body", AIOptions(headings=True)))

    def test_already_tagged_heading_always_qualifies(self):
        self.assertTrue(needs_ai_review("아무 표시 없는 제목", "heading", AIOptions(structure=True)))

    def test_long_terminal_body_paragraph_is_not_a_heading_candidate(self):
        text = "이 문단은 충분히 길고 마침표로 끝나기 때문에 제목 후보로 보이지 않아야 한다."
        self.assertFalse(needs_ai_review(text, "body", AIOptions(structure=True, headings=True)))

    def test_paren_triggers_glosses(self):
        self.assertTrue(needs_ai_review("정의(체다카)의 뜻이다.", "body", AIOptions(glosses=True)))
        self.assertFalse(needs_ai_review("정의(체다카)의 뜻이다.", "body", AIOptions(ocr_words=True)))

    def test_lone_unmatched_paren_still_triggers_glosses(self):
        # Exactly the OCR-damaged case worth sending to AI: the local
        # deterministic remover requires a balanced pair and skips this.
        self.assertTrue(needs_ai_review("정의(체다카의 뜻이다.", "body", AIOptions(glosses=True)))

    def test_paragraph_without_any_paren_is_skipped_for_glosses(self):
        self.assertFalse(needs_ai_review("정의는 체다카의 뜻이다.", "body", AIOptions(glosses=True)))
