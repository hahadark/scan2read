import unittest

from scan2read.cleanup.parentheses import remove_parenthetical


class RemoveParentheticalTests(unittest.TestCase):
    def test_strips_a_trailing_citation(self):
        self.assertEqual(remove_parenthetical("지라(계2:5)"), "지라")

    def test_strips_a_mid_sentence_citation_and_cleans_spacing(self):
        self.assertEqual(
            remove_parenthetical("그가 이르시되 내가 알파와 오메가라(계22:13)"),
            "그가 이르시되 내가 알파와 오메가라",
        )

    def test_removes_multiple_asides_and_collapses_spaces(self):
        self.assertEqual(remove_parenthetical("말했다(A) 그리고(B) 끝."), "말했다 그리고 끝.")

    def test_handles_nested_parentheses(self):
        self.assertEqual(remove_parenthetical("중첩(바깥(안쪽)바깥) 문장"), "중첩 문장")

    def test_full_width_parentheses_are_also_removed(self):
        self.assertEqual(remove_parenthetical("전각（테스트）문장"), "전각문장")

    def test_a_paragraph_that_is_entirely_parenthetical_becomes_empty(self):
        self.assertEqual(remove_parenthetical("(전체가 괄호)"), "")

    def test_no_parentheses_is_unchanged(self):
        self.assertEqual(remove_parenthetical("괄호 없음"), "괄호 없음")

    def test_unclosed_opening_paren_is_left_untouched(self):
        # An OCR misread easily drops one paren; deleting to the end of the
        # paragraph would destroy real content, so leave it as-is instead.
        text = "여는 괄호만 있음(안 닫힘"
        self.assertEqual(remove_parenthetical(text), text)

    def test_stray_closing_paren_is_left_untouched(self):
        text = "닫는 괄호만) 있음"
        self.assertEqual(remove_parenthetical(text), text)

    def test_whitespace_before_trailing_punctuation_is_cleaned_up(self):
        self.assertEqual(remove_parenthetical("문장이 끝난다 (참조)."), "문장이 끝난다.")
