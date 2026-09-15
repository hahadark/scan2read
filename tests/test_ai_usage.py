import unittest

from scan2read.cleanup.ai_providers import MODELS
from scan2read.cleanup.ai_usage import (AICostBudget, estimate_book_usage,
                                        estimate_epub_edit_usage, token_cost)


class AIUsageTests(unittest.TestCase):
    def test_official_luna_rates_and_cached_input_are_applied(self):
        self.assertAlmostEqual(token_cost(1_000_000, 1_000_000), 1.40)
        self.assertAlmostEqual(token_cost(1_000_000, 0, 1_000_000), 0.02)

    def test_a_different_models_rate_is_actually_used(self):
        opus = MODELS["anthropic:claude-opus-5"]
        self.assertNotAlmostEqual(token_cost(1_000_000, 1_000_000, model=opus), 1.40)
        self.assertAlmostEqual(token_cost(1_000_000, 1_000_000, model=opus),
                                opus.input_price + opus.output_price)

    def test_actual_usage_is_split_without_double_counting(self):
        snapshots=[];budget=AICostBudget(1.0,snapshots.append)
        budget.record(101,21,11,("ocr_words","spacing"))
        snapshot=budget.snapshot()
        self.assertEqual(snapshot["input_tokens"],101)
        self.assertEqual(sum(x["input_tokens"] for x in snapshot["features"].values()),101)
        self.assertEqual(sum(x["output_tokens"] for x in snapshot["features"].values()),21)
        self.assertEqual(len(snapshots),1)

    def test_request_that_could_cross_limit_is_blocked_before_transport(self):
        budget=AICostBudget(0.00001)
        self.assertFalse(budget.can_call("긴 입력"*100,1000,("boundary",)))
        self.assertTrue(budget.limit_reached);self.assertEqual(budget.cost_usd,0)

    def test_pre_conversion_estimate_reflects_enabled_features(self):
        boundary=estimate_book_usage(100,("boundary",))
        all_features=estimate_book_usage(100,("boundary","ocr_words","spacing","anomalies","structure","headings","glosses"))
        self.assertGreater(all_features.input_tokens,boundary.input_tokens)
        self.assertGreater(all_features.output_tokens,boundary.output_tokens)
        self.assertGreater(all_features.maximum_cost_usd,boundary.maximum_cost_usd)

    def test_glosses_increases_the_estimate(self):
        without=estimate_book_usage(100,("ocr_words",))
        with_glosses=estimate_book_usage(100,("ocr_words","glosses"))
        self.assertGreater(with_glosses.output_tokens,without.output_tokens)

    def test_reserve_blocks_a_second_concurrent_call_that_would_cross_the_limit(self):
        budget=AICostBudget(0.0005)
        first=budget.reserve("내용",100,("spacing",))
        self.assertIsNotNone(first)
        second=budget.reserve("내용",100,("spacing",))
        self.assertIsNone(second)
        self.assertTrue(budget.limit_reached)

    def test_record_releases_its_own_reservation_not_more(self):
        budget=AICostBudget(1.0)
        reserved=budget.reserve("x",10,("spacing",))
        self.assertGreater(reserved,0)
        self.assertAlmostEqual(budget.reserved_usd,reserved)
        budget.record(5,5,0,("spacing",),reserved=reserved)
        self.assertAlmostEqual(budget.reserved_usd,0.0)
        self.assertGreater(budget.cost_usd,0)

    def test_unlimited_budget_reserve_never_blocks(self):
        budget=AICostBudget(None)
        self.assertEqual(budget.reserve("x",100000,("spacing",)),0.0)

    def test_epub_edit_estimate_scales_with_the_book(self):
        small=estimate_epub_edit_usage(100,40_000)
        large=estimate_epub_edit_usage(1_000,400_000)
        self.assertGreater(large.input_tokens,small.input_tokens)
        self.assertGreater(large.maximum_cost_usd,small.maximum_cost_usd)

    def test_epub_edit_estimate_is_zero_for_an_empty_book(self):
        estimate=estimate_epub_edit_usage(0,0)
        self.assertEqual((estimate.input_tokens,estimate.output_tokens,estimate.maximum_cost_usd),(0,0,0.0))

    def test_epub_edit_worst_case_exceeds_the_typical_output(self):
        estimate=estimate_epub_edit_usage(500,200_000)
        self.assertGreater(estimate.maximum_cost_usd,
                            token_cost(estimate.input_tokens,estimate.output_tokens))
