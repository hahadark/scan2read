"""Token estimates, actual AI provider usage, and a per-book spending guard."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import threading
from typing import Callable, Iterable

from scan2read.cleanup.ai_providers import MODELS, DEFAULT_MODEL_KEY, ModelSpec

FEATURE_LABELS = {
    "boundary": "문단 경계 검사",
    "ocr_words": "OCR 의심 단어 보정",
    "spacing": "띄어쓰기 AI 재검사",
    "anomalies": "이상한 글자 탐지",
    "structure": "제목·본문·각주 분류",
    "headings": "장·절 구조 및 목차 감지",
    "glosses": "괄호·음역 중복 표현 삭제",
}


def token_cost(input_tokens: int, output_tokens: int, cached_input_tokens: int = 0,
               model: ModelSpec = MODELS[DEFAULT_MODEL_KEY]) -> float:
    """Calculate text cost from a provider's usage counters at `model`'s rates."""
    cached = max(0, min(int(cached_input_tokens), int(input_tokens)))
    uncached = max(0, int(input_tokens) - cached)
    return ((uncached * model.input_price
             + cached * model.cached_input_price
             + int(output_tokens) * model.output_price) / 1_000_000)


def conservative_input_tokens(text: str) -> int:
    """Upper-bound the visible request using UTF-8 bytes plus API framing slack."""
    return len(text.encode("utf-8")) + 768


@dataclass(frozen=True)
class UsageEstimate:
    input_tokens: int
    output_tokens: int
    maximum_cost_usd: float


def estimate_book_usage(page_count: int, features: Iterable[str],
                         model: ModelSpec = MODELS[DEFAULT_MODEL_KEY]) -> UsageEstimate:
    """Give a conservative pre-OCR estimate for an ordinary Korean printed page."""
    feature_set = set(features)
    pages = max(0, int(page_count))
    input_tokens = 0
    output_tokens = 0
    maximum_output_tokens = 0
    if "boundary" in feature_set:
        input_tokens += pages * 900
        output_tokens += pages * 45
        maximum_output_tokens += pages * 220
    cleanup = feature_set - {"boundary"}
    if cleanup:
        input_tokens += pages * 2_300
        output_per_page = 55
        if "ocr_words" in cleanup:
            output_per_page += 45
        if "spacing" in cleanup:
            output_per_page += 1_900
        if "anomalies" in cleanup:
            output_per_page += 35
        if "structure" in cleanup:
            output_per_page += 20
        if "headings" in cleanup:
            output_per_page += 15
        if "glosses" in cleanup:
            output_per_page += 30
        output_tokens += pages * output_per_page
        maximum_output_tokens += pages * max(output_per_page * 2, 280)
    maximum = token_cost(math.ceil(input_tokens * 1.35), maximum_output_tokens, model=model)
    return UsageEstimate(input_tokens, output_tokens, maximum)


@dataclass
class FeatureUsage:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class AICostBudget:
    """Share one hard API budget across every AI feature for one book.

    Thread-safe: `reserve()`/`record()` support firing several requests in
    parallel against one shared limit. `reserve()` locks in a request's
    conservative maximum cost *before* it is sent, so two concurrent
    requests can never both slip past the limit in the gap between checking
    and recording; `record()` releases that reservation and replaces it with
    the real, usage-based cost. `can_call()` remains for callers that only
    ever issue one request at a time (no reservation needed).
    """
    limit_usd: float | None = None
    callback: Callable[[dict], None] | None = None
    model: ModelSpec = MODELS[DEFAULT_MODEL_KEY]
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cost_usd: float = 0.0
    reserved_usd: float = 0.0
    limit_reached: bool = False
    features: dict[str, FeatureUsage] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def can_call(self, input_text: str, max_output_tokens: int, feature_names: Iterable[str]) -> bool:
        with self._lock:
            if self.limit_reached:
                return False
            if self.limit_usd is None:
                return True
            estimated_cost = token_cost(conservative_input_tokens(input_text), max_output_tokens,
                                         model=self.model)
            if self.cost_usd + self.reserved_usd + estimated_cost <= self.limit_usd + 1e-12:
                return True
            self.limit_reached = True
            self._notify()
            return False

    def reserve(self, input_text: str, max_output_tokens: int, feature_names: Iterable[str]) -> float | None:
        """Lock in this call's conservative maximum cost. Returns the
        reserved USD amount (0.0 when unlimited) to pass to `record()`, or
        None if sending would risk exceeding the limit -- the caller must
        not send the request in that case."""
        with self._lock:
            if self.limit_reached:
                return None
            if self.limit_usd is None:
                return 0.0
            estimated_cost = token_cost(conservative_input_tokens(input_text), max_output_tokens,
                                         model=self.model)
            if self.cost_usd + self.reserved_usd + estimated_cost <= self.limit_usd + 1e-12:
                self.reserved_usd += estimated_cost
                return estimated_cost
            self.limit_reached = True
            self._notify()
            return None

    @staticmethod
    def _split(total: int, names: list[str]) -> list[int]:
        quotient, remainder = divmod(max(0, int(total)), len(names))
        return [quotient + (index < remainder) for index in range(len(names))]

    def record(self, input_tokens: int, output_tokens: int, cached_input_tokens: int,
               feature_names: Iterable[str], reserved: float = 0.0) -> None:
        names = list(dict.fromkeys(feature_names))
        with self._lock:
            self.reserved_usd = max(0.0, self.reserved_usd - reserved)
            if not names:
                return
            input_tokens = int(input_tokens or 0)
            output_tokens = int(output_tokens or 0)
            cached_tokens = int(cached_input_tokens or 0)
            cost = token_cost(input_tokens, output_tokens, cached_tokens, model=self.model)
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.cached_input_tokens += cached_tokens
            self.cost_usd += cost
            input_parts = self._split(input_tokens, names)
            output_parts = self._split(output_tokens, names)
            cached_parts = self._split(cached_tokens, names)
            for index, name in enumerate(names):
                item = self.features.setdefault(name, FeatureUsage())
                item.requests += 1
                item.input_tokens += input_parts[index]
                item.output_tokens += output_parts[index]
                item.cached_input_tokens += cached_parts[index]
                item.cost_usd += token_cost(input_parts[index], output_parts[index], cached_parts[index],
                                             model=self.model)
            if self.limit_usd is not None and self.cost_usd >= self.limit_usd:
                self.limit_reached = True
            self._notify()

    def snapshot(self) -> dict:
        return {
            "provider": self.model.provider,
            "model": self.model.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "cost_usd": round(self.cost_usd, 8),
            "limit_usd": self.limit_usd,
            "limit_reached": self.limit_reached,
            "features": {
                name: {**vars(value), "cost_usd": round(value.cost_usd, 8)}
                for name, value in self.features.items()
            },
        }

    def _notify(self) -> None:
        if self.callback is not None:
            self.callback(self.snapshot())
