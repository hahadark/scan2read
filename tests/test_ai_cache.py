from pathlib import Path
import tempfile
import unittest

from scan2read.cleanup.ai_cache import AIResultCache, cache_key


class AICacheTests(unittest.TestCase):
    def test_missing_key_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(AIResultCache(Path(directory)).get("missing"))

    def test_set_then_get_roundtrips(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = AIResultCache(Path(directory))
            key = cache_key("gpt-5.6-luna", ("spacing",), "본문")
            cache.set(key, {"spacing_text": "본문"})
            self.assertEqual(cache.get(key), {"spacing_text": "본문"})

    def test_key_differs_by_text_features_and_model(self):
        base = cache_key("gpt-5.6-luna", ("spacing",), "본문")
        self.assertNotEqual(base, cache_key("gpt-5.6-luna", ("spacing",), "다른 본문"))
        self.assertNotEqual(base, cache_key("gpt-5.6-luna", ("ocr_words",), "본문"))
        self.assertNotEqual(base, cache_key("other-model", ("spacing",), "본문"))

    def test_key_is_stable_regardless_of_feature_order(self):
        a = cache_key("gpt-5.6-luna", ("spacing", "ocr_words"), "본문")
        b = cache_key("gpt-5.6-luna", ("ocr_words", "spacing"), "본문")
        self.assertEqual(a, b)

    def test_corrupted_cache_file_is_treated_as_a_miss(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            key = "deadbeef"
            (path / f"{key}.json").write_text("not json", encoding="utf-8")
            self.assertIsNone(AIResultCache(path).get(key))
