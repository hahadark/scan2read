import json
import unittest
import urllib.error

from scan2read.cleanup.ai_providers import (
    AIConnectionError, AnthropicProvider, GoogleProvider, OpenAIProvider,
    build_provider, check_access, default_model, model_key, models_for,
    resolve_model, MODELS,
)

SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"items": {"type": "array", "items": {"type": "object"}}},
          "required": ["items"]}


class OpenAIProviderTests(unittest.TestCase):
    def test_request_shape_and_response_parsing(self):
        captured = []
        def transport(payload):
            captured.append(payload)
            return {"output": [{"type": "message", "content": [
                        {"type": "output_text", "text": json.dumps({"items": []})}]}],
                    "usage": {"input_tokens": 10, "output_tokens": 5,
                              "input_tokens_details": {"cached_tokens": 2}}}
        provider = OpenAIProvider("secret", model="gpt-5.6-luna", transport=transport)
        result = provider.complete("instructions", "[]", SCHEMA, 300)
        self.assertEqual(json.loads(result.text), {"items": []})
        self.assertEqual((result.input_tokens, result.output_tokens, result.cached_input_tokens), (10, 5, 2))
        payload = captured[0]
        self.assertEqual(payload["model"], "gpt-5.6-luna")
        self.assertIs(payload["store"], False)
        self.assertEqual(payload["reasoning"]["effort"], "none")
        self.assertEqual(payload["text"]["format"]["schema"], SCHEMA)

    def test_missing_output_text_raises(self):
        provider = OpenAIProvider("secret", transport=lambda payload: {"output": []})
        with self.assertRaises(ValueError):
            provider.complete("i", "[]", SCHEMA, 300)

    def test_reasoning_effort_follows_the_model(self):
        captured = []
        def transport(payload):
            captured.append(payload)
            return {"output": [{"type": "message", "content": [
                        {"type": "output_text", "text": "{}"}]}], "usage": {}}
        for model, expected in (("gpt-5.6-luna", "none"), ("gpt-5.6-terra", "none")):
            captured.clear()
            OpenAIProvider("k", model=model, transport=transport).complete("i", "[]", SCHEMA, 300)
            self.assertEqual(captured[0]["reasoning"]["effort"], expected, model)

    def test_explicit_reasoning_effort_overrides_the_registry(self):
        # Models differ on which values they accept (gpt-6-astra rejects
        # "none" outright), so the caller must be able to set it.
        captured = []
        def transport(payload):
            captured.append(payload)
            return {"output": [{"type": "message", "content": [
                        {"type": "output_text", "text": "{}"}]}], "usage": {}}
        OpenAIProvider("k", model="gpt-5.6-luna", transport=transport,
                        reasoning_effort="low").complete("i", "[]", SCHEMA, 300)
        self.assertEqual(captured[0]["reasoning"]["effort"], "low")

    def test_unknown_model_omits_reasoning_rather_than_guessing(self):
        captured = []
        def transport(payload):
            captured.append(payload)
            return {"output": [{"type": "message", "content": [
                        {"type": "output_text", "text": "{}"}]}], "usage": {}}
        OpenAIProvider("k", model="gpt-7-unreleased", transport=transport).complete("i", "[]", SCHEMA, 300)
        self.assertNotIn("reasoning", captured[0])


class AnthropicProviderTests(unittest.TestCase):
    def test_request_shape_and_response_parsing(self):
        captured = []
        def transport(payload):
            captured.append(payload)
            return {"content": [{"type": "tool_use", "name": "emit_result", "input": {"items": []}}],
                    "usage": {"input_tokens": 8, "output_tokens": 4, "cache_read_input_tokens": 1}}
        provider = AnthropicProvider("secret", model="claude-sonnet-5", transport=transport)
        result = provider.complete("instructions", "[]", SCHEMA, 300)
        self.assertEqual(json.loads(result.text), {"items": []})
        self.assertEqual((result.input_tokens, result.output_tokens, result.cached_input_tokens), (8, 4, 1))
        payload = captured[0]
        self.assertEqual(payload["model"], "claude-sonnet-5")
        self.assertEqual(payload["system"], "instructions")
        self.assertEqual(payload["tool_choice"], {"type": "tool", "name": "emit_result"})
        self.assertEqual(payload["tools"][0]["input_schema"], SCHEMA)

    def test_missing_tool_use_raises(self):
        provider = AnthropicProvider("secret", transport=lambda payload: {"content": []})
        with self.assertRaises(ValueError):
            provider.complete("i", "[]", SCHEMA, 300)


class GoogleProviderTests(unittest.TestCase):
    def test_request_strips_additional_properties_and_parses_response(self):
        captured = []
        def transport(payload):
            captured.append(payload)
            return {"candidates": [{"content": {"parts": [{"text": json.dumps({"items": []})}]}}],
                    "usageMetadata": {"promptTokenCount": 6, "candidatesTokenCount": 3}}
        provider = GoogleProvider("secret", model="gemini-2.5-flash", transport=transport)
        result = provider.complete("instructions", "[]", SCHEMA, 300)
        self.assertEqual(json.loads(result.text), {"items": []})
        self.assertEqual((result.input_tokens, result.output_tokens, result.cached_input_tokens), (6, 3, 0))
        schema_sent = captured[0]["generationConfig"]["responseSchema"]
        self.assertNotIn("additionalProperties", schema_sent)
        self.assertEqual(captured[0]["generationConfig"]["responseMimeType"], "application/json")

    def test_missing_candidate_text_raises(self):
        provider = GoogleProvider("secret", transport=lambda payload: {"candidates": []})
        with self.assertRaises(ValueError):
            provider.complete("i", "[]", SCHEMA, 300)


class RegistryTests(unittest.TestCase):
    def test_openai_luna_rate_is_the_confirmed_one(self):
        spec = MODELS["openai:gpt-5.6-luna"]
        self.assertTrue(spec.verified)
        self.assertEqual((spec.input_price, spec.cached_input_price, spec.output_price), (0.20, 0.02, 1.20))

    def test_expensive_openai_models_are_not_offered(self):
        # Measured on a real 5-page run: 16x (sol) and 36x (astra) Luna's cost
        # for the same mechanical cleanup. Dropped deliberately, not by
        # oversight -- re-adding needs a fresh cost/benefit measurement.
        self.assertNotIn("openai:gpt-6-astra", MODELS)
        self.assertNotIn("openai:gpt-5.6-sol", MODELS)

    def test_every_registry_model_has_published_rates(self):
        self.assertGreaterEqual(len(MODELS), 10)
        for key, spec in MODELS.items():
            self.assertTrue(spec.verified, key)
            self.assertEqual(key, model_key(spec.provider, spec.model))
            self.assertGreater(spec.input_price, 0.0, key)
            self.assertGreater(spec.output_price, 0.0, key)
            # Output always costs more than input; a swapped pair would make
            # the budget wildly optimistic on exactly the expensive side.
            self.assertGreater(spec.output_price, spec.input_price, key)
            self.assertLess(spec.cached_input_price, spec.input_price, key)

    def test_all_three_providers_offer_a_choice_of_models(self):
        for provider in ("openai", "anthropic", "google"):
            self.assertGreaterEqual(len(models_for(provider)), 2, provider)

    def test_unknown_model_id_is_approximated_and_flagged_unverified(self):
        spec = resolve_model("anthropic", "claude-not-a-real-model")
        self.assertFalse(spec.verified)
        self.assertEqual(spec.model, "claude-not-a-real-model")
        self.assertGreater(spec.input_price, 0.0)

    def test_unknown_model_borrows_the_worst_case_same_provider_rate(self):
        # Guessing low would overspend silently; guessing high only stops early.
        # Google is the case that matters: its priciest input (gemini-3.6-flash)
        # and priciest output (gemini-2.5-pro) are different models, so taking
        # one model's whole row would understate the other rate.
        spec = resolve_model("google", "gemini-unknown")
        specs = models_for("google")
        self.assertEqual(spec.input_price, max(s.input_price for s in specs))
        self.assertEqual(spec.output_price, max(s.output_price for s in specs))

    def test_each_provider_defaults_to_a_cheap_model_not_its_flagship(self):
        for provider in ("openai", "anthropic", "google"):
            spec = resolve_model(provider, default_model(provider))
            priciest = max(models_for(provider), key=lambda s: s.output_price)
            self.assertLess(spec.output_price, priciest.output_price, provider)

    def test_models_for_filters_by_provider(self):
        anthropic_models = models_for("anthropic")
        self.assertTrue(all(spec.provider == "anthropic" for spec in anthropic_models))
        self.assertGreaterEqual(len(anthropic_models), 2)

    def test_model_key_round_trips_into_the_registry(self):
        self.assertIn(model_key("google", "gemini-2.5-flash"), MODELS)

    def test_build_provider_dispatches_by_name(self):
        self.assertIsInstance(build_provider("openai", "gpt-5.6-luna", "k"), OpenAIProvider)
        self.assertIsInstance(build_provider("anthropic", "claude-sonnet-5", "k"), AnthropicProvider)
        self.assertIsInstance(build_provider("google", "gemini-2.5-flash", "k"), GoogleProvider)
        with self.assertRaises(ValueError):
            build_provider("unknown", "x", "k")


class Reply:
    def __init__(self, body):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def read(self, *_):
        return self.body


class CheckAccessTests(unittest.TestCase):
    def test_openai_confirms_via_model_lookup(self):
        requests = []
        def opener(request, timeout):
            requests.append(request)
            return Reply(b'{"id":"gpt-5.6-luna"}')
        check_access("openai", "gpt-5.6-luna", "secret", opener=opener)
        self.assertEqual(requests[0].get_method(), "GET")
        self.assertIn("gpt-5.6-luna", requests[0].full_url)

    def test_anthropic_confirms_via_minimal_completion(self):
        requests = []
        def opener(request, timeout):
            requests.append(request)
            return Reply(b'{"content":[],"usage":{}}')
        check_access("anthropic", "claude-sonnet-5", "secret", opener=opener)
        self.assertEqual(requests[0].get_method(), "POST")
        self.assertEqual(requests[0].get_header("X-api-key"), "secret")

    def test_google_confirms_via_model_lookup(self):
        requests = []
        def opener(request, timeout):
            requests.append(request)
            return Reply(b'{"name":"models/gemini-2.5-flash"}')
        check_access("google", "gemini-2.5-flash", "secret", opener=opener)
        self.assertEqual(requests[0].get_method(), "GET")

    def test_unauthorized_key_raises_readable_error(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)
        with self.assertRaises(AIConnectionError):
            check_access("openai", "gpt-5.6-luna", "bad-key", opener=opener)
