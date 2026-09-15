"""Whole-book EPUB editing driven by one natural-language rule.

Deliberately a different safety model from `ai_enhance.py`. That module
repairs OCR damage and therefore never lets the model rewrite prose: every
proposal has to survive a deterministic validator. Here the user is *asking*
for rewrites ("각주 번호 빼줘"), so the model is allowed to replace or delete a
block outright -- and the safety comes from somewhere else entirely:

- nothing is ever written to the source file; edits go to a new EPUB;
- this module only *proposes*. Applying is a separate step, after a human
  has seen the before/after list (`cli.py`'s --plan-only / --apply-plan).

Works with any AIProvider from `cleanup/ai_providers.py`.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import logging
import threading
import time

logger = logging.getLogger(__name__)

MAX_RULE_CHARS = 600
_MAX_BLOCK_CHARS = 2000


@dataclass(frozen=True)
class Change:
    """One proposed edit. `after` is None for a deletion."""
    document: str
    index: int
    before: str
    after: str | None

    def as_dict(self) -> dict:
        return {"document": self.document, "index": self.index,
                "before": self.before, "after": self.after}

    @classmethod
    def from_dict(cls, data: dict) -> "Change":
        return cls(data["document"], int(data["index"]), data["before"], data["after"])


_SCHEMA = {"type": "object", "additionalProperties": False,
           "properties": {"items": {"type": "array", "items": {
               "type": "object", "additionalProperties": False,
               "properties": {"id": {"type": "integer"},
                              "action": {"type": "string", "enum": ["keep", "replace", "delete"]},
                              "text": {"type": ["string", "null"]}},
               "required": ["id", "action", "text"]}}},
           "required": ["items"]}


class EpubRuleEditor:
    """Ask the model, block by block, what the user's rule implies."""

    def __init__(self, provider, rule: str, batch_size: int = 16, budget=None,
                 max_parallel: int = 3, progress=None):
        self.provider = provider
        self.rule = rule.strip()[:MAX_RULE_CHARS]
        self.batch_size = batch_size
        self.budget = budget
        self.max_parallel = max(1, max_parallel)
        self.progress = progress
        self.disabled = False
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self._lock = threading.Lock()
        self._total = 0
        self._completed = 0
        self._start = None

    def _instructions(self) -> str:
        return ("한국어 전자책의 문단을 사용자가 정한 규칙에 따라 고친다. "
                "각 문단마다 action을 고른다: 규칙과 무관하면 keep, 규칙에 따라 내용을 "
                "바꿔야 하면 replace(바뀐 전체 문장을 text에 담는다), 규칙에 따라 통째로 "
                "빼야 하면 delete(text는 null). keep일 때도 text는 null로 둔다. "
                "규칙이 요구하지 않은 문단은 절대 바꾸지 않는다. 맞춤법이나 문체를 임의로 "
                "손보지 않는다. 사용자 규칙: " + self.rule)

    def _report(self, advance=False):
        with self._lock:
            if advance:
                self._completed += 1
            if self.progress is None:
                return
            completed, total = self._completed, self._total
            elapsed = time.monotonic() - self._start if self._start else 0.0
            remaining = round(elapsed / completed * (total - completed), 1) if completed and total > completed else None
            self.progress({"stage": "epub_edit", "completed_batches": completed, "total_batches": total,
                           "elapsed_seconds": round(elapsed, 1), "estimated_remaining_seconds": remaining})

    def _call_batch(self, batch, collected):
        try:
            if self.disabled:
                return
            items = [{"id": i, "text": block.text[:_MAX_BLOCK_CHARS]} for i, block in batch]
            input_json = json.dumps(items, ensure_ascii=False)
            instructions = self._instructions()
            limit = max(600, min(32000, sum(len(item["text"]) for item in items) + 200 * len(items)))
            try:
                reserved = 0.0
                if self.budget is not None:
                    reserved = self.budget.reserve(instructions + input_json, limit, ("epub_edit",))
                    if reserved is None:
                        self.disabled = True
                        logger.warning("AI cost limit reached; stopping EPUB edit planning")
                        return
                response = self.provider.complete(instructions, input_json, _SCHEMA, limit)
                if self.budget is not None:
                    self.budget.record(response.input_tokens, response.output_tokens,
                                       response.cached_input_tokens, ("epub_edit",), reserved=reserved)
                returned = {item["id"]: item for item in json.loads(response.text)["items"]}
                if set(returned) != {i for i, _ in batch}:
                    raise ValueError("EPUB edit response omitted or added IDs")
                with self._lock:
                    self.usage["input_tokens"] += response.input_tokens
                    self.usage["output_tokens"] += response.output_tokens
                    for i, block in batch:
                        item = returned[i]
                        change = self._change_for(block, item)
                        if change is not None:
                            collected.append(change)
            except OSError as exc:
                logger.warning("EPUB edit connection failed; stopping: %s", exc)
                self.disabled = True
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                # Only this batch is lost; its blocks simply keep their text.
                logger.warning("EPUB edit response invalid for this batch; skipping it: %s", exc)
        finally:
            self._report(advance=True)

    @staticmethod
    def _change_for(block, item) -> Change | None:
        action = item.get("action")
        if action == "delete":
            return Change(block.document, block.index, block.text, None)
        if action == "replace":
            text = item.get("text")
            if isinstance(text, str) and text.strip() and text.strip() != block.text.strip():
                return Change(block.document, block.index, block.text, text.strip())
        return None

    def plan(self, blocks) -> list[Change]:
        """Proposed changes only -- this never touches a file."""
        indexed = [(i, block) for i, block in enumerate(blocks) if block.text.strip()]
        batches = [indexed[start:start + self.batch_size]
                   for start in range(0, len(indexed), self.batch_size)]
        collected: list[Change] = []
        if not batches:
            return []
        self._total = len(batches)
        self._completed = 0
        self._start = time.monotonic()
        self._report()
        with ThreadPoolExecutor(max_workers=min(self.max_parallel, len(batches))) as executor:
            list(executor.map(lambda batch: self._call_batch(batch, collected), batches))
        return sorted(collected, key=lambda change: (change.document, change.index))
