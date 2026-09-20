"""Tests for app/llm.py's model-response-parsing layer.

Every real LLMClient implementation (currently AnthropicClient; an earlier
iteration of this module targeted Gemini via Vertex AI, see
docs/ai-usage.md) does two things: call the model, then hand the raw JSON
to one of parse_redaction_response / parse_classification_response /
parse_extraction_response. Those three functions are pure (no network, no
SDK) and provider-agnostic -- the JSON contract they validate comes from
prompts/*.md, not from any one provider's SDK -- which is what this file
exercises, using response shapes taken straight from each prompt file's
own worked example, plus deliberately-malformed variants a real model
response could plausibly return.

What this file does NOT and cannot cover: an actual call to a model
provider. See tests/test_llm_anthropic_client_wiring.py for coverage of
AnthropicClient's SDK-calling code against a faked SDK, and
docs/ai-usage.md for why the real network call has not been exercised
from either sandbox this project was built in.
"""
import unittest

from app.llm import (
    RedactionResult,
    parse_classification_response,
    parse_extraction_response,
    parse_redaction_response,
)


class ParseRedactionResponseTests(unittest.TestCase):
    def test_worked_example_from_prompt_file(self):
        # Straight from prompts/redaction_v1.md's own worked example.
        data = {
            "redacted_text": (
                "A [REDACTED] [person] was seen unloading sacks into the empty "
                "house on our street around 2am."
            ),
            "categories_redacted": ["ethnicity_tribe", "stranger_or_foreigner_markers"],
        }
        result = parse_redaction_response(data)
        self.assertIsInstance(result, RedactionResult)
        self.assertEqual(result.redacted_text, data["redacted_text"])
        self.assertEqual(result.categories_redacted, ["ethnicity_tribe", "stranger_or_foreigner_markers"])
        self.assertTrue(result.was_redacted)

    def test_no_categories_matched(self):
        data = {"redacted_text": "Someone was checking gates along Alade Street.", "categories_redacted": []}
        result = parse_redaction_response(data)
        self.assertFalse(result.was_redacted)

    def test_duplicate_categories_are_deduped_in_order(self):
        data = {
            "redacted_text": "[REDACTED] [REDACTED] man seen loitering.",
            "categories_redacted": ["nationality", "religion", "nationality"],
        }
        result = parse_redaction_response(data)
        self.assertEqual(result.categories_redacted, ["nationality", "religion"])

    def test_unknown_category_key_is_rejected(self):
        data = {"redacted_text": "x", "categories_redacted": ["disability"]}
        with self.assertRaises(ValueError):
            parse_redaction_response(data)

    def test_missing_redacted_text_key_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_redaction_response({"categories_redacted": []})

    def test_missing_categories_key_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_redaction_response({"redacted_text": "x"})

    def test_wrong_type_for_redacted_text_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_redaction_response({"redacted_text": None, "categories_redacted": []})

    def test_wrong_type_for_categories_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_redaction_response({"redacted_text": "x", "categories_redacted": "nationality"})

    def test_non_dict_response_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_redaction_response(["not", "a", "dict"])


class ParseClassificationResponseTests(unittest.TestCase):
    def test_worked_example_protected(self):
        self.assertEqual(parse_classification_response({"channel": "protected"}), "protected")

    def test_worked_example_normal(self):
        self.assertEqual(parse_classification_response({"channel": "normal"}), "normal")

    def test_invalid_channel_value_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_classification_response({"channel": "urgent"})

    def test_missing_channel_key_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_classification_response({})

    def test_null_channel_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_classification_response({"channel": None})

    def test_non_dict_response_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_classification_response("protected")


class ParseExtractionResponseTests(unittest.TestCase):
    def test_worked_example_from_prompt_file(self):
        # Straight from prompts/extraction_v1.md's own worked example.
        data = {"scores": {"burglary_casing": 1, "explosives_storage": 0}, "time_of_day": "night"}
        scores = parse_extraction_response(data, expected_pattern_ids=["burglary_casing", "explosives_storage"])
        self.assertEqual(scores, {"burglary_casing": 1, "explosives_storage": 0})

    def test_time_of_day_is_dropped_even_when_present(self):
        # app/extraction.py computes time_of_day itself (_TIME_HINTS regex);
        # a model's own guess must never leak through this function.
        data = {"scores": {"burglary_casing": 2}, "time_of_day": "definitely not a real value"}
        scores = parse_extraction_response(data, expected_pattern_ids=["burglary_casing"])
        self.assertNotIn("time_of_day", scores)

    def test_missing_pattern_id_defaults_to_zero(self):
        # A pattern the model doesn't mention at all is "no evidence", same
        # as an explicit 0 -- ambient noise must still score 0 everywhere.
        data = {"scores": {"burglary_casing": 1}}
        scores = parse_extraction_response(data, expected_pattern_ids=["burglary_casing", "explosives_storage"])
        self.assertEqual(scores, {"burglary_casing": 1, "explosives_storage": 0})

    def test_extra_pattern_id_not_requested_is_ignored(self):
        data = {"scores": {"burglary_casing": 1, "some_future_pattern": 9}}
        scores = parse_extraction_response(data, expected_pattern_ids=["burglary_casing"])
        self.assertEqual(scores, {"burglary_casing": 1})

    def test_negative_score_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_extraction_response({"scores": {"burglary_casing": -1}}, expected_pattern_ids=["burglary_casing"])

    def test_non_int_score_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_extraction_response({"scores": {"burglary_casing": "high"}}, expected_pattern_ids=["burglary_casing"])

    def test_boolean_score_is_rejected(self):
        # bool is a subclass of int in Python -- must be excluded explicitly.
        with self.assertRaises(ValueError):
            parse_extraction_response({"scores": {"burglary_casing": True}}, expected_pattern_ids=["burglary_casing"])

    def test_missing_scores_key_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_extraction_response({}, expected_pattern_ids=["burglary_casing"])

    def test_wrong_type_for_scores_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_extraction_response({"scores": "none"}, expected_pattern_ids=["burglary_casing"])

    def test_non_dict_response_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_extraction_response(None, expected_pattern_ids=["burglary_casing"])


if __name__ == "__main__":
    unittest.main()
