"""Exercises AnthropicClient's wiring against a fake Anthropic SDK.

The `anthropic` package cannot be installed in this sandbox -- there is no
route to pypi.org (confirmed by direct request, see docs/ai-usage.md) --
so there is no way to test this class against the real SDK from here, even
though api.anthropic.com itself IS reachable (a direct request to it
returns 401 without a key, i.e. a real, responsive endpoint -- a notably
better starting point than the Gemini/Vertex AI path an earlier iteration
of this module took, where the host itself was blocked outright).

This file substitutes a minimal fake for the `anthropic` module via
sys.modules, matching the real SDK's documented shape
(`anthropic.Anthropic(api_key=...).messages.create(model=, max_tokens=,
system=, messages=[...])`, returning an object whose `.content` is a list
of blocks with a `.text` attribute), so it can prove app/llm.py calls the
SDK correctly and that a canned JSON reply flows through to
redact()/classify_channel()/score_patterns()'s return values, including
the error paths (empty content, malformed JSON, a markdown-fenced reply,
a raised SDK exception).

This does NOT prove the real `anthropic` package behaves the way this
fake stands in for it -- only scripts/smoke_test_claude.py, run on a
machine with the SDK installed and a real API key, can do that. What this
file proves is that app/llm.py's own code is wired correctly against the
SDK's documented interface.
"""
import importlib
import sys
import types
import unittest


class FakeContentBlock:
    def __init__(self, text):
        self.text = text


class FakeMessage:
    def __init__(self, text):
        self.content = [FakeContentBlock(text)] if text is not None else []


class FakeMessagesResource:
    """Stands in for an anthropic.Anthropic client's `.messages` resource."""

    def __init__(self):
        self.calls = []
        self._next_response_text = "{}"

    def create(self, model, max_tokens, system, messages):
        self.calls.append({"model": model, "max_tokens": max_tokens, "system": system, "messages": messages})
        return FakeMessage(self._next_response_text)


class FakeAnthropic:
    """Stands in for anthropic.Anthropic."""

    instances = []

    def __init__(self, api_key=None, **kwargs):
        self.api_key = api_key
        self.kwargs = kwargs
        self.messages = FakeMessagesResource()
        FakeAnthropic.instances.append(self)


class AnthropicClientWiringTests(unittest.TestCase):
    def setUp(self):
        FakeAnthropic.instances = []

        fake_anthropic_module = types.ModuleType("anthropic")
        fake_anthropic_module.Anthropic = FakeAnthropic
        self.fake_anthropic_module = fake_anthropic_module

        self._patched = {"anthropic": fake_anthropic_module}
        self._orig = {name: sys.modules.get(name) for name in self._patched}
        sys.modules.update(self._patched)

        # Re-import app.llm fresh so its `import anthropic` picks up the
        # fake module above rather than any real one already cached.
        sys.modules.pop("app.llm", None)
        self.llm_module = importlib.import_module("app.llm")

    def tearDown(self):
        for name, mod in self._orig.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        sys.modules.pop("app.llm", None)
        importlib.import_module("app.llm")  # restore the real module for anything imported later

    def _make_client(self):
        return self.llm_module.AnthropicClient(api_key="test-api-key", model_name="claude-test-model")

    def test_init_constructs_anthropic_client_with_api_key(self):
        client = self._make_client()
        self.assertEqual(len(FakeAnthropic.instances), 1)
        self.assertIs(client._client, FakeAnthropic.instances[0])
        self.assertEqual(client._client.api_key, "test-api-key")

    def test_missing_api_key_raises_before_touching_the_sdk(self):
        with self.assertRaises(RuntimeError):
            self.llm_module.AnthropicClient(api_key="")
        self.assertEqual(len(FakeAnthropic.instances), 0)

    def test_redact_round_trip_through_fake_sdk(self):
        client = self._make_client()
        client._client.messages._next_response_text = (
            '{"redacted_text": "A [REDACTED] [person] was seen loitering.", '
            '"categories_redacted": ["ethnicity_tribe", "stranger_or_foreigner_markers"]}'
        )
        result = client.redact("A Fulani stranger was seen loitering.", terms={})
        self.assertEqual(result.categories_redacted, ["ethnicity_tribe", "stranger_or_foreigner_markers"])
        self.assertTrue(result.was_redacted)

        call = client._client.messages.calls[0]
        self.assertEqual(call["model"], "claude-test-model")
        self.assertEqual(call["system"], client._redaction_prompt)
        self.assertEqual(call["messages"], [{"role": "user", "content": "A Fulani stranger was seen loitering."}])

    def test_classify_channel_round_trip_through_fake_sdk(self):
        client = self._make_client()
        client._client.messages._next_response_text = '{"channel": "protected"}'
        channel = client.classify_channel("The gateman is asking for a bribe.", protected_indicator_terms=[])
        self.assertEqual(channel, "protected")
        self.assertEqual(client._client.messages.calls[0]["system"], client._classification_prompt)

    def test_score_patterns_round_trip_through_fake_sdk_and_serialises_patterns(self):
        client = self._make_client()
        client._client.messages._next_response_text = (
            '{"scores": {"burglary_casing": 1, "explosives_storage": 0}, "time_of_day": "night"}'
        )
        scores = client.score_patterns(
            "Someone was checking gates along Alade Street late last night.",
            pattern_keywords={"burglary_casing": ["checking gates"], "explosives_storage": ["chemical drums"]},
        )
        self.assertEqual(scores, {"burglary_casing": 1, "explosives_storage": 0})
        self.assertNotIn("time_of_day", scores)

        call = client._client.messages.calls[0]
        self.assertEqual(call["system"], client._extraction_prompt)
        user_content = call["messages"][0]["content"]
        self.assertIn("burglary_casing", user_content)
        self.assertIn("checking gates", user_content)
        self.assertIn("Someone was checking gates", user_content)

    def test_markdown_fenced_json_response_is_still_parsed(self):
        # Defensive path in _generate_json: some models wrap JSON output in
        # a ```json fence even when the prompt asks for bare JSON.
        client = self._make_client()
        client._client.messages._next_response_text = '```json\n{"channel": "normal"}\n```'
        self.assertEqual(client.classify_channel("ordinary report", protected_indicator_terms=[]), "normal")

    def test_empty_content_raises_runtime_error(self):
        client = self._make_client()
        client._client.messages._next_response_text = None
        with self.assertRaises(RuntimeError):
            client.classify_channel("x", protected_indicator_terms=[])

    def test_malformed_json_response_raises_runtime_error(self):
        client = self._make_client()
        client._client.messages._next_response_text = "not json at all"
        with self.assertRaises(RuntimeError):
            client.classify_channel("x", protected_indicator_terms=[])

    def test_sdk_exception_during_create_is_wrapped(self):
        client = self._make_client()

        def _raise(*args, **kwargs):
            raise ConnectionError("simulated network failure")

        client._client.messages.create = _raise
        with self.assertRaises(RuntimeError):
            client.classify_channel("x", protected_indicator_terms=[])


if __name__ == "__main__":
    unittest.main()
