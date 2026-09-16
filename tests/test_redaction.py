"""CLAUDE.md required tests:
- A report naming nationality, tribe or religion is redacted before
  clustering, and the identity text never reaches the pattern store.
- "Stranger seen after curfew" is reduced to observed behaviour only.
"""
import unittest

from app.config import get_config
from app.llm import RuleBasedClient
from app.redaction import redact_report_text


class RedactionTests(unittest.TestCase):
    def setUp(self):
        self.config = get_config()
        self.llm = RuleBasedClient()

    def test_nationality_ethnicity_religion_are_redacted(self):
        text = "A Nigerian Yoruba Muslim man was seen unloading sacks into the empty house."
        result = redact_report_text(text, "en-NG", self.config, self.llm)
        self.assertTrue(result.was_redacted)
        self.assertIn("nationality", result.categories_redacted)
        self.assertIn("ethnicity_tribe", result.categories_redacted)
        self.assertIn("religion", result.categories_redacted)
        # The identity terms themselves must not survive into the redacted
        # text that gets persisted (app/pipeline.py only ever stores this
        # redacted string -- the raw text is never written to storage).
        for term in ("Nigerian", "Yoruba", "Muslim"):
            self.assertNotIn(term, result.text)

    def test_stranger_seen_after_curfew_reduces_to_behaviour(self):
        text = "Stranger seen after curfew loitering near gate 2."
        result = redact_report_text(text, "en-NG", self.config, self.llm)
        self.assertTrue(result.was_redacted)
        self.assertIn("stranger_or_foreigner_markers", result.categories_redacted)
        self.assertNotIn("Stranger", result.text)
        self.assertNotIn("stranger", result.text.lower())
        # The behaviour -- loitering, near gate 2, after curfew -- survives.
        self.assertIn("loitering", result.text.lower())
        self.assertIn("gate 2", result.text.lower())
        self.assertIn("curfew", result.text.lower())

    def test_no_false_positive_on_ordinary_words_containing_a_term(self):
        # Regression test: "Tiv" (ethnicity_tribe) must not match inside
        # "operatives" or "relatives" -- caught during seed replay, see
        # docs/ai-usage.md.
        text = "Amotekun operatives visited his relatives at the checkpoint."
        result = redact_report_text(text, "en-NG", self.config, self.llm)
        self.assertFalse(result.was_redacted)
        self.assertEqual(result.text, text)

    def test_clean_report_is_not_redacted(self):
        text = "Two men were photographing the houses along the street from a parked car."
        result = redact_report_text(text, "en-NG", self.config, self.llm)
        self.assertFalse(result.was_redacted)
        self.assertEqual(result.categories_redacted, [])


if __name__ == "__main__":
    unittest.main()
