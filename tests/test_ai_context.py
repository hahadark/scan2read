import json
import unittest

from scan2read.cleanup.ai_context import AIContextJoiner
from scan2read.cleanup.ai_providers import OpenAIProvider
from scan2read.cleanup.context import ContextJoiner
from scan2read.cleanup.ai_usage import AICostBudget


def response(decisions):
    return {"output": [{"type": "message", "content": [
        {"type": "output_text", "text": json.dumps({"decisions": decisions})}
    ]}]}


def provider(transport, model="gpt-5.6-luna"):
    return OpenAIProvider("secret", model=model, transport=transport)


class AIContextTests(unittest.TestCase):
    def test_cost_limit_falls_back_before_api_call(self):
        calls=[]
        joiner=AIContextJoiner(provider(lambda payload:calls.append(payload)),budget=AICostBudget(0))
        self.assertEqual(joiner.decide_many([("계속되는 표현","다음 내용")]),[False])
        self.assertEqual(calls,[]);self.assertEqual(joiner.disabled_reason,"cost_limit")

    def test_luna_batches_only_ambiguous_boundaries_and_never_rewrites(self):
        payloads = []
        def transport(payload):
            payloads.append(payload)
            candidates = json.loads(payload["input"])
            return response([{"id": item["id"], "join": True} for item in candidates])

        joiner = AIContextJoiner(provider(transport), ContextJoiner())
        result = joiner.decide_many([
            ("완결된 문장이다.", "새 문단이다."),
            ("이 표현에는 아직 계속될 내용", "설명으로 이어진다."),
            ("저자의", "설명이다."),
        ])

        self.assertEqual(result, [False, True, True])
        self.assertEqual(len(payloads), 1)
        self.assertEqual([item["id"] for item in json.loads(payloads[0]["input"])], [1])
        self.assertEqual(payloads[0]["model"], "gpt-5.6-luna")
        self.assertIs(payloads[0]["store"], False)
        self.assertEqual(payloads[0]["reasoning"]["effort"], "none")

    def test_luna_failure_falls_back_without_joining_ambiguous_boundary(self):
        calls = []
        def fail(_payload):
            calls.append(True)
            raise OSError("offline")

        joiner = AIContextJoiner(provider(fail), batch_size=1)
        self.assertEqual(joiner.decide_many([("끝나지 않은 표현", "다음 내용"),
                                              ("계속되는 내용", "또 다음 내용")]), [False, False])
        self.assertEqual(len(calls), 1)
        self.assertEqual(joiner.audit_records[-1]["source"], "fallback")

    def test_a_malformed_response_only_skips_its_own_batch_not_the_rest_of_the_book(self):
        # Real-book regression: the very first of 4,194 boundary decisions in
        # a 554-page book got a response with a mismatched ID set, and the
        # old code silently fell back the remaining 3,405 decisions for the
        # rest of the book on that single hiccup.
        calls = []
        def transport(payload):
            calls.append(payload)
            candidates = json.loads(payload["input"])
            if len(calls) == 1:
                return response([{"id": candidates[0]["id"] + 999, "join": True}])  # wrong id
            return response([{"id": item["id"], "join": True} for item in candidates])
        joiner = AIContextJoiner(provider(transport), batch_size=1)
        result = joiner.decide_many([("끝나지 않은 표현", "다음 내용"), ("계속되는 내용", "또 다음 내용")])
        self.assertEqual(len(calls), 2)  # the second batch was still attempted
        self.assertIsNone(joiner.disabled_reason)
        self.assertEqual(result, [False, True])

    def test_progress_reports_zero_of_n_then_each_batch_completing(self):
        reports = []
        def transport(payload):
            candidates = json.loads(payload["input"])
            return response([{"id": item["id"], "join": True} for item in candidates])
        joiner = AIContextJoiner(provider(transport), batch_size=1, progress=reports.append)
        joiner.decide_many([("끝나지 않은 표현", "다음 내용"), ("계속되는 내용", "또 다음 내용")])
        self.assertEqual([r["completed_batches"] for r in reports], [0, 1, 2])
        self.assertTrue(all(r["total_batches"] == 2 for r in reports))
        self.assertTrue(all(r["stage"] == "ai_context" for r in reports))

    def test_no_ambiguous_boundaries_reports_zero_of_zero(self):
        reports = []
        joiner = AIContextJoiner(provider(lambda payload: None), progress=reports.append)
        joiner.decide_many([("완결된 문장이다.", "새 문단이다.")])
        self.assertEqual(reports, [{"stage": "ai_context", "completed_batches": 0, "total_batches": 0,
            "elapsed_seconds": reports[0]["elapsed_seconds"], "estimated_remaining_seconds": None}])
