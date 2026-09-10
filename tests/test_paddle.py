import unittest
from scan2read.ocr.paddle import convert_result


class PaddleTests(unittest.TestCase):
    def test_conversion_and_order(self):
        result = {"rec_texts": ["아래", "위"], "rec_scores": [.9, .8],
                  "rec_polys": [[[1, 30], [50, 30], [50, 40], [1, 40]],
                                [[1, 10], [50, 10], [50, 20], [1, 20]]]}
        page = convert_result(result, 100, 100)
        self.assertEqual([b.text for b in page.blocks], ["위", "아래"])
        self.assertEqual(page.blocks[0].bbox, (1, 10, 50, 20))

    def test_incomplete_result_rejected(self):
        with self.assertRaises(ValueError):
            convert_result({"rec_texts": ["x"], "rec_scores": [], "rec_polys": []}, 100, 100)
