"""Optional AI-assisted paragraph-boundary decisions.

Only short text excerpts are sent. The model returns join/no-join decisions and
is never allowed to rewrite OCR text. Works with any AIProvider (OpenAI,
Anthropic, Google) from `cleanup/ai_providers.py`.
"""
import json
import logging
import time

from scan2read.cleanup.context import ContextJoiner, _TERMINAL


logger = logging.getLogger(__name__)


class AIContextJoiner:
    """Use the configured AI provider for ambiguous boundaries, falling back
    to the local joiner."""

    def __init__(self, provider, local: ContextJoiner | None = None,
                 batch_size: int = 32, budget=None, progress=None):
        self.provider = provider
        self.local = local or ContextJoiner()
        self.batch_size = batch_size
        self.budget = budget
        self.progress = progress
        self.audit_records: list[dict] = []
        self.disabled_reason: str | None = None
        self._connected_logged = False

    def _report_progress(self, completed: int, total: int, start_time: float) -> None:
        if self.progress is None:
            return
        elapsed = time.monotonic() - start_time
        remaining = round(elapsed / completed * (total - completed), 1) if completed and total > completed else None
        self.progress({"stage": "ai_context", "completed_batches": completed, "total_batches": total,
                       "elapsed_seconds": round(elapsed, 1), "estimated_remaining_seconds": remaining})

    @staticmethod
    def _excerpt(text: str, left: bool) -> str:
        clean = " ".join(text.split())
        return clean[-240:] if left else clean[:240]

    _SCHEMA = {"type": "object", "additionalProperties": False,
               "properties": {"decisions": {"type": "array", "items": {
                   "type": "object", "additionalProperties": False,
                   "properties": {"id": {"type": "integer"}, "join": {"type": "boolean"}},
                   "required": ["id", "join"]}}},
               "required": ["decisions"]}
    _INSTRUCTIONS = (
        "한국어 책 OCR의 문단 경계를 판정한다. 각 left와 right가 원래 한 문단인데 "
        "스캔 페이지, 단 나눔, 잘못된 줄바꿈 때문에 분리된 경우에만 join=true로 답한다. "
        "제목, 목록, 완결된 문장, 실제 새 문단은 false다. 문장을 교정하거나 다시 쓰지 않는다.")

    def _request(self, candidates: list[tuple[int, str, str]]):
        boundaries = [{"id": identifier, "left": self._excerpt(left, True), "right": self._excerpt(right, False)}
                      for identifier, left, right in candidates]
        max_output_tokens = max(160, min(1200, 48 * len(boundaries) + 80))
        return self.provider.complete(self._INSTRUCTIONS, json.dumps(boundaries, ensure_ascii=False),
                                       self._SCHEMA, max_output_tokens)

    def decide_many(self, pairs: list[tuple[str, str]]) -> list[bool]:
        decisions = [False] * len(pairs)
        pending: list[tuple[int, str, str]] = []
        for index, (left, right) in enumerate(pairs):
            if self.local(left, right):
                decisions[index] = True
                self.audit_records.append({"index": index, "source": "local", "join": True})
            elif left.rstrip() and right.lstrip() and not _TERMINAL.search(left.rstrip()):
                pending.append((index, left, right))
            else:
                self.audit_records.append({"index": index, "source": "local", "join": False})

        total_batches = -(-len(pending) // self.batch_size) if pending else 0
        start_time = time.monotonic()
        self._report_progress(0, total_batches, start_time)
        for batch_number, start in enumerate(range(0, len(pending), self.batch_size), 1):
            batch = pending[start:start + self.batch_size]
            try:
                if self.disabled_reason:
                    for identifier, _, _ in batch:
                        self.audit_records.append({"index": identifier, "source": "fallback",
                                                   "join": False, "error": self.disabled_reason})
                    continue
                try:
                    max_output_tokens = max(160, min(1200, 48 * len(batch) + 80))
                    if self.budget is not None:
                        input_preview = json.dumps(
                            [{"id": i, "left": self._excerpt(left, True), "right": self._excerpt(right, False)}
                             for i, left, right in batch], ensure_ascii=False) + self._INSTRUCTIONS
                        if not self.budget.can_call(input_preview, max_output_tokens, ("boundary",)):
                            self.disabled_reason = "cost_limit"
                            logger.warning("AI cost limit reached; using local paragraph decisions")
                            for identifier, _, _ in batch:
                                self.audit_records.append({"index": identifier, "source": "fallback",
                                                           "join": False, "error": self.disabled_reason})
                            continue
                    response = self._request(batch)
                    if self.budget is not None:
                        self.budget.record(response.input_tokens, response.output_tokens,
                                            response.cached_input_tokens, ("boundary",))
                    parsed = json.loads(response.text)
                    returned = {item["id"]: item["join"] for item in parsed["decisions"]
                                if isinstance(item.get("id"), int) and isinstance(item.get("join"), bool)}
                    expected = {identifier for identifier, _, _ in batch}
                    if set(returned) != expected:
                        raise ValueError("AI response omitted or added boundary IDs")
                    if not self._connected_logged:
                        logger.info("AI provider connected: context checking is active")
                        self._connected_logged = True
                    for identifier, left, right in batch:
                        decisions[identifier] = returned[identifier]
                        self.audit_records.append({"index": identifier, "source": "ai",
                                                   "join": returned[identifier],
                                                   "left": self._excerpt(left, True),
                                                   "right": self._excerpt(right, False)})
                except OSError as exc:
                    # Connection/HTTP-level failure (also covers urllib's
                    # HTTPError/URLError, both OSError subclasses) -- the
                    # service itself is unreachable or erroring, likely to
                    # keep failing, so stop sending new batches for the rest
                    # of this book.
                    logger.warning("AI context check connection failed; disabling remaining boundary checks: %s", exc)
                    self.disabled_reason = type(exc).__name__
                    for identifier, _, _ in batch:
                        self.audit_records.append({"index": identifier, "source": "fallback",
                                                   "join": False, "error": self.disabled_reason})
                except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                    # The request reached the service fine; this response just
                    # didn't parse or validate (e.g. a one-off ID mismatch).
                    # Real-book regression: the very first of 4,194 boundary
                    # decisions hit this, and the old code treated it as
                    # permanent, silently falling back the remaining 3,405
                    # decisions for the rest of a 554-page book. Only this
                    # batch falls back now; the next batch gets a fresh try.
                    logger.warning("AI context response invalid for this batch; using local decisions: %s", exc)
                    for identifier, _, _ in batch:
                        self.audit_records.append({"index": identifier, "source": "fallback",
                                                   "join": False, "error": type(exc).__name__})
            finally:
                self._report_progress(batch_number, total_batches, start_time)
        return decisions
