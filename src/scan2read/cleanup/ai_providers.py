"""Vendor-specific AI backends behind one small interface.

Mirrors the `OCREngine` pattern in `ocr/base.py`: a thin `Protocol` so
`ai_context.py`/`ai_enhance.py`'s batching, budget, cache, retry-classification,
and progress-reporting logic stays completely vendor-agnostic, and only the
vendor-specific request shape / response parsing lives here.

PRICING: every MODELS entry's input/output rate comes from the vendor's
published September 2026 pricing (`gpt-5.6-luna`'s was additionally
confirmed against real API usage in this project). Cached-input rates are
published for the OpenAI lineup and Anthropic; Google's are derived from the
25% context-caching ratio Google publishes for 2.5 Flash. Rates move -- the
cost-limit feature exists to protect real spending, so re-check these when a
book's reported cost looks off, and note `gemini-3.8-flash` is on
introductory pricing that doubles on 2027-01-01.
"""
from dataclasses import dataclass
import json
import urllib.error
import urllib.request


@dataclass(frozen=True)
class ProviderResponse:
    """Normalized result: a JSON-parseable string plus usage in one shape,
    regardless of which vendor produced it."""
    text: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    label: str
    input_price: float  # USD per 1,000,000 input tokens
    cached_input_price: float
    output_price: float  # USD per 1,000,000 output tokens
    verified: bool = True
    # OpenAI only. Cleanup is a mechanical rewrite, so we ask for the least
    # reasoning each model allows -- reasoning tokens bill as output. The
    # accepted values differ per model: the 5.6 family takes "none", while
    # gpt-6-astra rejects it (400, "Supported values are: 'low', 'medium',
    # 'high', 'xhigh', 'max'"), which is why this is per-model and why an
    # unlisted model omits the field instead of guessing.
    reasoning_effort: str | None = None


MODELS: dict[str, ModelSpec] = {
    # OpenAI. Cached input is 10% of input. GPT-6 Astra and GPT-5.6 Sol are
    # deliberately not listed: a measured 5-page run cost 16x and 36x Luna's
    # for the same mechanical cleanup, which does not pay for itself here.
    "openai:gpt-5.6-terra": ModelSpec(
        "openai", "gpt-5.6-terra", "OpenAI GPT-5.6 Terra (균형)", 2.00, 0.20, 12.00,
        reasoning_effort="none"),
    "openai:gpt-5.6-luna": ModelSpec(
        "openai", "gpt-5.6-luna", "OpenAI GPT-5.6 Luna (저비용, 이 앱 기본값)",
        0.20, 0.02, 1.20, reasoning_effort="none"),
    # Anthropic. Cache reads are 10% of input except Fable 5.1, which
    # Anthropic cut to 2.5% ($0.25 against $10.00 input).
    "anthropic:claude-fable-5-1": ModelSpec(
        "anthropic", "claude-fable-5-1", "Claude Fable 5.1 (최고 성능)", 10.00, 0.25, 50.00),
    "anthropic:claude-opus-5": ModelSpec(
        "anthropic", "claude-opus-5", "Claude Opus 5", 5.00, 0.50, 25.00),
    "anthropic:claude-sonnet-5": ModelSpec(
        "anthropic", "claude-sonnet-5", "Claude Sonnet 5 (균형)", 3.00, 0.30, 15.00),
    "anthropic:claude-haiku-4-5-20251001": ModelSpec(
        "anthropic", "claude-haiku-4-5-20251001", "Claude Haiku 4.5 (저비용)",
        1.00, 0.10, 5.00),
    # Google. Input/output are published; cached input is 25% of input, the
    # ratio Google publishes for 2.5 Flash context caching.
    "google:gemini-3.8-flash": ModelSpec(
        "google", "gemini-3.8-flash", "Gemini 3.8 Flash (최신, 도입가: 2027-01-01 2배 인상 예정)",
        0.75, 0.1875, 3.75),
    "google:gemini-3.6-flash": ModelSpec(
        "google", "gemini-3.6-flash", "Gemini 3.6 Flash", 1.50, 0.375, 7.50),
    "google:gemini-2.5-pro": ModelSpec(
        "google", "gemini-2.5-pro", "Gemini 2.5 Pro", 1.25, 0.3125, 10.00),
    "google:gemini-2.5-flash": ModelSpec(
        "google", "gemini-2.5-flash", "Gemini 2.5 Flash (균형)", 0.30, 0.075, 2.50),
    "google:gemini-2.5-flash-lite": ModelSpec(
        "google", "gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite (저비용)",
        0.10, 0.025, 0.40),
}

# A batch can ask for up to 32k output tokens, and the bigger models take
# minutes to produce that. At 60s, gpt-5.6-sol and gpt-6-astra both timed out
# on a real 5-page batch -- and a timeout is an OSError, which disables AI
# cleanup for the rest of the book, so a too-short timeout silently downgrades
# whole conversions on exactly the models the user paid more for.
REQUEST_TIMEOUT = 300

DEFAULT_MODEL_KEY = "openai:gpt-5.6-luna"

# Per-provider default: the cheap/balanced model, never the flagship. Books
# run to hundreds of pages, so silently defaulting to a 50x-pricier model
# because it happens to be listed first would be an expensive surprise.
DEFAULT_MODEL_FOR = {
    "openai": "gpt-5.6-luna",
    "anthropic": "claude-sonnet-5",
    "google": "gemini-2.5-flash",
}


def models_for(provider: str) -> list[ModelSpec]:
    return [spec for spec in MODELS.values() if spec.provider == provider]


def default_model(provider: str) -> str | None:
    name = DEFAULT_MODEL_FOR.get(provider)
    if name is not None:
        return name
    specs = models_for(provider)
    return specs[0].model if specs else None


def model_key(provider: str, model: str) -> str:
    return f"{provider}:{model}"


def resolve_model(provider: str, model: str) -> ModelSpec:
    """Look up pricing for `provider:model`. A user can type any model ID
    (the GUI's model field is deliberately editable, since our guessed IDs
    for anything but gpt-5.6-luna may be wrong) -- for an ID outside the
    registry, borrow another model's rate from the same provider as a rough
    approximation rather than refusing to convert, and mark it unverified."""
    spec = MODELS.get(model_key(provider, model))
    if spec is not None:
        return spec
    same_provider = models_for(provider)
    if same_provider:
        # Worst case across the provider, each rate taken independently (the
        # priciest input and priciest output need not be the same model): an
        # unknown ID's real cost is unknown, and for a spending guard
        # overestimating only stops the run early, while underestimating
        # overspends silently.
        return ModelSpec(provider, model, f"{model} (단가 미확인, {provider} 최고 단가로 근사)",
                          max(s.input_price for s in same_provider),
                          max(s.cached_input_price for s in same_provider),
                          max(s.output_price for s in same_provider), verified=False)
    return ModelSpec(provider, model, f"{model} (단가 미확인)", 0.0, 0.0, 0.0, verified=False)


def _http_post_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST", headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


class OpenAIProvider:
    """Moved unchanged from the old OpenAILuna* classes' inline request code."""
    endpoint = "https://api.openai.com/v1/responses"

    def __init__(self, api_key: str, model: str = "gpt-5.6-luna",
                 timeout: float = REQUEST_TIMEOUT, transport=None, reasoning_effort: str = "auto"):
        self.api_key = api_key.strip()
        self.model = model
        self.timeout = timeout
        self.transport = transport or self._request
        if reasoning_effort == "auto":
            spec = MODELS.get(model_key("openai", model))
            # Unknown model: omit the field rather than guess a value it may
            # reject, since the accepted set differs per model.
            reasoning_effort = spec.reasoning_effort if spec else None
        self.reasoning_effort = reasoning_effort

    def _request(self, payload: dict) -> dict:
        return _http_post_json(self.endpoint, payload,
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            self.timeout)

    def complete(self, instructions: str, input_json: str, schema: dict,
                 max_output_tokens: int) -> ProviderResponse:
        payload = {
            "model": self.model, "store": False,
            "max_output_tokens": max_output_tokens, "instructions": instructions,
            "input": input_json,
            "text": {"format": {"type": "json_schema", "name": "book_cleanup",
                                 "strict": True, "schema": schema}},
        }
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        response = self.transport(payload)
        text = None
        for item in response.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    text = content.get("text", "")
        if text is None:
            raise ValueError("OpenAI response did not contain output text")
        usage = response.get("usage", {})
        details = usage.get("input_tokens_details", {}) or {}
        return ProviderResponse(text, int(usage.get("input_tokens", 0) or 0),
                                 int(usage.get("output_tokens", 0) or 0),
                                 int(details.get("cached_tokens", 0) or 0))


class AnthropicProvider:
    """Claude via the Messages API. Structured output is obtained by forcing
    a single tool call whose input_schema is our schema -- Claude has no
    separate "strict JSON schema" response mode, but a forced tool call is
    Anthropic's own documented way to get schema-conforming JSON reliably."""
    endpoint = "https://api.anthropic.com/v1/messages"
    api_version = "2023-06-01"

    def __init__(self, api_key: str, model: str = "claude-sonnet-5",
                 timeout: float = REQUEST_TIMEOUT, transport=None):
        self.api_key = api_key.strip()
        self.model = model
        self.timeout = timeout
        self.transport = transport or self._request

    def _request(self, payload: dict) -> dict:
        return _http_post_json(self.endpoint, payload,
            {"x-api-key": self.api_key, "anthropic-version": self.api_version,
             "Content-Type": "application/json"}, self.timeout)

    def complete(self, instructions: str, input_json: str, schema: dict,
                 max_output_tokens: int) -> ProviderResponse:
        payload = {
            "model": self.model, "max_tokens": max_output_tokens,
            "system": instructions,
            "messages": [{"role": "user", "content": input_json}],
            "tools": [{"name": "emit_result", "description": "Return the structured cleanup result.",
                       "input_schema": schema}],
            "tool_choice": {"type": "tool", "name": "emit_result"},
        }
        response = self.transport(payload)
        result = None
        for block in response.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == "emit_result":
                result = block.get("input")
        if result is None:
            raise ValueError("Claude response did not contain a tool_use result")
        usage = response.get("usage", {})
        return ProviderResponse(json.dumps(result, ensure_ascii=False),
                                 int(usage.get("input_tokens", 0) or 0),
                                 int(usage.get("output_tokens", 0) or 0),
                                 int(usage.get("cache_read_input_tokens", 0) or 0))


def _strip_unsupported_schema_keywords(node):
    """Gemini's responseSchema dialect rejects keywords like
    additionalProperties that OpenAI/Anthropic's strict schemas rely on."""
    if isinstance(node, dict):
        cleaned = {key: _strip_unsupported_schema_keywords(value) for key, value in node.items()
                   if key not in ("additionalProperties",)}
        return cleaned
    if isinstance(node, list):
        return [_strip_unsupported_schema_keywords(item) for item in node]
    return node


class GoogleProvider:
    """Gemini via the Generative Language API's generateContent endpoint."""
    endpoint_template = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash",
                 timeout: float = REQUEST_TIMEOUT, transport=None):
        self.api_key = api_key.strip()
        self.model = model
        self.timeout = timeout
        self.transport = transport or self._request

    def _request(self, payload: dict) -> dict:
        url = self.endpoint_template.format(model=self.model) + f"?key={self.api_key}"
        return _http_post_json(url, payload, {"Content-Type": "application/json"}, self.timeout)

    def complete(self, instructions: str, input_json: str, schema: dict,
                 max_output_tokens: int) -> ProviderResponse:
        payload = {
            "system_instruction": {"parts": [{"text": instructions}]},
            "contents": [{"role": "user", "parts": [{"text": input_json}]}],
            "generationConfig": {
                "maxOutputTokens": max_output_tokens,
                "responseMimeType": "application/json",
                "responseSchema": _strip_unsupported_schema_keywords(schema),
            },
        }
        response = self.transport(payload)
        try:
            text = response["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise ValueError("Gemini response did not contain candidate text") from exc
        usage = response.get("usageMetadata", {})
        return ProviderResponse(text, int(usage.get("promptTokenCount", 0) or 0),
                                 int(usage.get("candidatesTokenCount", 0) or 0), 0)


_PROVIDER_CLASSES = {"openai": OpenAIProvider, "anthropic": AnthropicProvider, "google": GoogleProvider}


def build_provider(provider: str, model: str, api_key: str, timeout: float = REQUEST_TIMEOUT, transport=None):
    try:
        cls = _PROVIDER_CLASSES[provider]
    except KeyError:
        raise ValueError(f"Unknown AI provider: {provider!r}") from None
    return cls(api_key, model=model, timeout=timeout, transport=transport)


class AIConnectionError(RuntimeError):
    pass


def check_access(provider: str, model: str, api_key: str, timeout: float = 15,
                  opener=urllib.request.urlopen) -> None:
    """Validate authentication and model access, as cheaply as each vendor's
    API allows. OpenAI and Google expose a free model-info GET; Anthropic has
    no equivalent, so its check is a 1-token completion (a negligible but
    non-zero cost)."""
    api_key = api_key.strip()
    label = MODELS.get(model_key(provider, model))
    label = label.label if label else model
    try:
        if provider == "openai":
            request = urllib.request.Request(
                f"https://api.openai.com/v1/models/{model}", method="GET",
                headers={"Authorization": f"Bearer {api_key}"})
            with opener(request, timeout=timeout) as response:
                data = json.load(response)
            if data.get("id") != model:
                raise AIConnectionError(f"{label} 모델 정보를 확인하지 못했습니다.")
        elif provider == "anthropic":
            request = urllib.request.Request(
                "https://api.anthropic.com/v1/messages", method="POST",
                data=json.dumps({"model": model, "max_tokens": 1,
                                  "messages": [{"role": "user", "content": "hi"}]}).encode("utf-8"),
                headers={"x-api-key": api_key, "anthropic-version": AnthropicProvider.api_version,
                         "Content-Type": "application/json"})
            with opener(request, timeout=timeout) as response:
                json.load(response)
        elif provider == "google":
            request = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}?key={api_key}",
                method="GET")
            with opener(request, timeout=timeout) as response:
                data = json.load(response)
            if model not in (data.get("name") or ""):
                raise AIConnectionError(f"{label} 모델 정보를 확인하지 못했습니다.")
        else:
            raise ValueError(f"Unknown AI provider: {provider!r}")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise AIConnectionError("API 키가 올바르지 않습니다.") from exc
        if exc.code in (403, 404):
            raise AIConnectionError(f"이 API 계정에서 {label}을(를) 사용할 수 없습니다.") from exc
        raise AIConnectionError(f"서버 오류가 발생했습니다 (HTTP {exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise AIConnectionError("서버에 연결할 수 없습니다. 인터넷 연결을 확인하세요.") from exc
