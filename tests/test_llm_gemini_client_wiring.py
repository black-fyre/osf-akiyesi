"""Exercises VertexGeminiClient's wiring against a fake Vertex AI SDK.

Neither sandbox this project was built in (this one, or the developer's
own device sandbox) has network access to generativelanguage.googleapis.com
or aiplatform.googleapis.com (see docs/ai-usage.md) -- so there is no way
to test this class against the real API from here. This file substitutes a
minimal fake for the `vertexai` / `vertexai.generative_models` modules via
sys.modules, so it can prove app/llm.py calls the SDK the way its
documented contract requires: vertexai.init(project=..., location=...),
one GenerativeModel per prompt file with that file's content as
system_instruction, generate_content(..., generation_config=
GenerationConfig(response_mime_type="application/json", temperature=0)),
and that a canned JSON reply flows correctly through to
redact()/classify_channel()/score_patterns()'s return values, including
the error paths (empty response, malformed JSON, a markdown-fenced reply,
an SDK exception).

This does NOT prove the real Vertex AI SDK behaves the way this fake
stands in for it -- only scripts/smoke_test_gemini.py, run on a machine
with real GCP credentials and network access, can do that. What this file
proves is that app/llm.py's own code is wired correctly against the SDK's
documented interface.
"""
import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeGenerativeModel:
    """Stands in for vertexai.generative_models.GenerativeModel.

    Records constructor args and lets each test control what
    generate_content returns for that particular model instance.
    """

    instances = []

    def __init__(self, model_name, system_instruction=None):
        self.model_name = model_name
        self.system_instruction = system_instruction
        self.generate_content_calls = []
        self._next_response_text = "{}"
        FakeGenerativeModel.instances.append(self)

    def generate_content(self, user_content, generation_config=None):
        self.generate_content_calls.append((user_content, generation_config))
        return FakeResponse(self._next_response_text)


class FakeGenerationConfig:
    def __init__(self, response_mime_type=None, temperature=None):
        self.response_mime_type = response_mime_type
        self.temperature = temperature


class VertexGeminiClientWiringTests(unittest.TestCase):
    def setUp(self):
        FakeGenerativeModel.instances = []

        fake_generative_models = types.ModuleType("vertexai.generative_models")
        fake_generative_models.GenerativeModel = FakeGenerativeModel
        fake_generative_models.GenerationConfig = FakeGenerationConfig

        fake_vertexai = types.ModuleType("vertexai")
        fake_vertexai.init = MagicMock()
        fake_vertexai.generative_models = fake_generative_models

        self.fake_vertexai = fake_vertexai
        self.fake_generative_models = fake_generative_models

        self._patched = {"vertexai": fake_vertexai, "vertexai.generative_models": fake_generative_models}
        self._orig = {name: sys.modules.get(name) for name in self._patched}
        sys.modules.update(self._patched)

        # Re-import app.llm fresh so its `import vertexai` picks up the
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
        return self.llm_module.VertexGeminiClient(
            project_id="test-project", location="us-central1", model_name="gemini-test-model"
        )

    def test_init_calls_vertexai_init_with_project_and_location(self):
        self._make_client()
        self.fake_vertexai.init.assert_called_once_with(project="test-project", location="us-central1")

    def test_three_models_built_with_correct_system_instructions(self):
        client = self._make_client()
        self.assertEqual(len(FakeGenerativeModel.instances), 3)
        self.assertEqual(client._redaction_model.system_instruction, client._redaction_prompt)
        self.assertEqual(client._classification_model.system_instruction, client._classification_prompt)
        self.assertEqual(client._extraction_model.system_instruction, client._extraction_prompt)
        for inst in FakeGenerativeModel.instances:
            self.assertEqual(inst.model_name, "gemini-test-model")

    def test_missing_project_id_raises_before_touching_the_sdk(self):
        with self.assertRaises(RuntimeError):
            self.llm_module.VertexGeminiClient(project_id="")
        self.fake_vertexai.init.assert_not_called()

    def test_redact_round_trip_through_fake_sdk(self):
        client = self._make_client()
        client._redaction_model._next_response_text = (
            '{"redacted_text": "A [REDACTED] [person] was seen loitering.", '
            '"categories_redacted": ["ethnicity_tribe", "stranger_or_foreigner_markers"]}'
        )
        result = client.redact("A Fulani stranger was seen loitering.", terms={})
        self.assertEqual(result.categories_redacted, ["ethnicity_tribe", "stranger_or_foreigner_markers"])
        self.assertTrue(result.was_redacted)

        call_content, call_config = client._redaction_model.generate_content_calls[0]
        self.assertEqual(call_content, "A Fulani stranger was seen loitering.")
        self.assertEqual(call_config.response_mime_type, "application/json")
        self.assertEqual(call_config.temperature, 0)

    def test_classify_channel_round_trip_through_fake_sdk(self):
        client = self._make_client()
        client._classification_model._next_response_text = '{"channel": "protected"}'
        channel = client.classify_channel("The gateman is asking for a bribe.", protected_indicator_terms=[])
        self.assertEqual(channel, "protected")

    def test_score_patterns_round_trip_through_fake_sdk_and_serialises_patterns(self):
        client = self._make_client()
        client._extraction_model._next_response_text = (
            '{"scores": {"burglary_casing": 1, "explosives_storage": 0}, "time_of_day": "night"}'
        )
        scores = client.score_patterns(
            "Someone was checking gates along Alade Street late last night.",
            pattern_keywords={"burglary_casing": ["checking gates"], "explosives_storage": ["chemical drums"]},
        )
        self.assertEqual(scores, {"burglary_casing": 1, "explosives_storage": 0})
        self.assertNotIn("time_of_day", scores)

        call_content, _ = client._extraction_model.generate_content_calls[0]
        self.assertIn("burglary_casing", call_content)
        self.assertIn("checking gates", call_content)
        self.assertIn("Someone was checking gates", call_content)

    def test_markdown_fenced_json_response_is_still_parsed(self):
        # Defensive path in _generate_json: some models wrap JSON output in
        # a ```json fence even when response_mime_type asked for bare JSON.
        client = self._make_client()
        client._classification_model._next_response_text = '```json\n{"channel": "normal"}\n```'
        self.assertEqual(client.classify_channel("ordinary report", protected_indicator_terms=[]), "normal")

    def test_empty_response_text_raises_runtime_error(self):
        client = self._make_client()
        client._classification_model._next_response_text = ""
        with self.assertRaises(RuntimeError):
            client.classify_channel("x", protected_indicator_terms=[])

    def test_malformed_json_response_raises_runtime_error(self):
        client = self._make_client()
        client._classification_model._next_response_text = "not json at all"
        with self.assertRaises(RuntimeError):
            client.classify_channel("x", protected_indicator_terms=[])

    def test_sdk_exception_during_generate_content_is_wrapped(self):
        client = self._make_client()

        def _raise(*args, **kwargs):
            raise ConnectionError("simulated network failure")

        client._classification_model.generate_content = _raise
        with self.assertRaises(RuntimeError):
            client.classify_channel("x", protected_indicator_terms=[])


if __name__ == "__main__":
    unittest.main()
