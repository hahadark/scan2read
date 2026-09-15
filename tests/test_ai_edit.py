import json
import unittest

from scan2read.cleanup.ai_edit import Change, EpubRuleEditor
from scan2read.cleanup.ai_providers import OpenAIProvider
from scan2read.cleanup.ai_usage import AICostBudget
from scan2read.epub.editor import Block


def response(items, input_tokens=100, output_tokens=20):
    return {"output": [{"type": "message", "content": [{"type": "output_text",
            "text": json.dumps({"items": items}, ensure_ascii=False)}]}],
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}}


def provider(transport):
    return OpenAIProvider("secret", model="gpt-5.6-luna", transport=transport)


def blocks(*texts):
    return [Block("EPUB/chapter.xhtml", i, text) for i, text in enumerate(texts)]


class EpubRuleEditorTests(unittest.TestCase):
    def test_keep_replace_and_delete_become_changes(self):
        def transport(payload):
            sent = json.loads(payload["input"])
            return response([
                {"id": sent[0]["id"], "action": "keep", "text": None},
                {"id": sent[1]["id"], "action": "replace", "text": "고친 문장"},
                {"id": sent[2]["id"], "action": "delete", "text": None},
            ])
        editor = EpubRuleEditor(provider(transport), "각주 번호는 빼주세요")
        changes = editor.plan(blocks("그대로", "원래 문장", "1)"))
        self.assertEqual([(c.index, c.after) for c in changes], [(1, "고친 문장"), (2, None)])

    def test_the_rule_is_sent_in_the_instructions(self):
        captured = []
        def transport(payload):
            captured.append(payload["instructions"])
            sent = json.loads(payload["input"])
            return response([{"id": item["id"], "action": "keep", "text": None} for item in sent])
        EpubRuleEditor(provider(transport), "영어 인용문은 통째로 빼주세요").plan(blocks("문단"))
        self.assertIn("영어 인용문은 통째로 빼주세요", captured[0])

    def test_a_replace_identical_to_the_original_is_not_a_change(self):
        def transport(payload):
            sent = json.loads(payload["input"])
            return response([{"id": sent[0]["id"], "action": "replace", "text": " 같은 문장 "}])
        editor = EpubRuleEditor(provider(transport), "규칙")
        self.assertEqual(editor.plan(blocks("같은 문장")), [])

    def test_cost_limit_stops_planning_without_proposing_anything(self):
        calls = []
        editor = EpubRuleEditor(provider(lambda payload: calls.append(payload)), "규칙",
                                budget=AICostBudget(0))
        self.assertEqual(editor.plan(blocks("문단")), [])
        self.assertEqual(calls, [])
        self.assertTrue(editor.disabled)

    def test_a_malformed_batch_is_skipped_rather_than_guessed_at(self):
        def transport(payload):
            return response([{"id": 999, "action": "delete", "text": None}])
        editor = EpubRuleEditor(provider(transport), "규칙")
        self.assertEqual(editor.plan(blocks("문단")), [])
        self.assertFalse(editor.disabled)

    def test_a_connection_failure_stops_the_rest_of_the_book(self):
        def transport(payload):
            raise OSError("network unreachable")
        editor = EpubRuleEditor(provider(transport), "규칙", batch_size=1)
        self.assertEqual(editor.plan(blocks("하나", "둘")), [])
        self.assertTrue(editor.disabled)

    def test_an_overlong_rule_is_clipped(self):
        editor = EpubRuleEditor(provider(lambda payload: None), "가" * 5000)
        self.assertLess(len(editor.rule), 5000)


class ChangeTests(unittest.TestCase):
    def test_round_trips_through_json(self):
        original = Change("EPUB/a.xhtml", 2, "이전", None)
        restored = Change.from_dict(json.loads(json.dumps(original.as_dict(), ensure_ascii=False)))
        self.assertEqual(restored, original)


if __name__ == "__main__":
    unittest.main()
