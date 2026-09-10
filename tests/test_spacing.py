import unittest
from scan2read.cleanup.spacing import correct_spacing


class SpacingTests(unittest.TestCase):
    def test_korean_spaces_only(self):
        self.assertEqual(correct_spacing("성서본문을읽는다", lambda _: "성서 본문을 읽는다"), "성서 본문을 읽는다")
        self.assertEqual(correct_spacing("성 서 본문", lambda _: "성서 본문"), "성서 본문")

    def test_reject_letter_number_punctuation_changes(self):
        for candidate in ["바뀐 본문", "성서 본문!", "성서 본문2", "성서\t본문"]:
            self.assertEqual(correct_spacing("성서본문", lambda _: candidate), "성서본문")

    def test_protect_citations(self):
        text = "성서본문 John Smith (롬 4:24)"
        proposed = "성서 본문 JohnSmith (롬4:24)"
        self.assertEqual(correct_spacing(text, lambda _: proposed), "성서 본문 John Smith (롬 4:24)")
