"""Pattern extraction tests (app/extraction.py), including the new
weapon_sighting pattern (config/patterns.yaml) added for the high-signal
escalation pathway (see docs/ai-usage.md).
"""
import unittest

from app.config import get_config
from app.extraction import UNCLASSIFIED, extract
from app.llm import RuleBasedClient


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.config = get_config()
        self.community = self.config.community_by_id("oke-ado-phase2")
        self.llm = RuleBasedClient()

    def _extract(self, text):
        return extract(text, self.community, self.config, self.llm)

    def test_burglary_casing_still_matches(self):
        # Regression: adding weapon_sighting must not change scoring for
        # the existing patterns.
        result = self._extract("Someone was checking gates along Alade Street block by block.")
        self.assertEqual(result.pattern_id, "burglary_casing")

    def test_weapon_keyword_matches_weapon_sighting(self):
        result = self._extract("Two men were seen carrying a gun near the fence around 9pm.")
        self.assertEqual(result.pattern_id, "weapon_sighting")
        self.assertGreaterEqual(result.pattern_score, 1)

    def test_robbers_keyword_matches_weapon_sighting(self):
        result = self._extract("A group of robbers with a machete attacked a passerby on the main road.")
        self.assertEqual(result.pattern_id, "weapon_sighting")

    def test_unarmed_does_not_false_positive_on_armed_keyword(self):
        # Deliberate keyword choice: config/patterns.yaml's weapon_sighting
        # list uses "gun", "weapon", "robbers" etc. rather than "armed men"
        # or "armed robbers", specifically because RuleBasedClient.score_patterns
        # does a plain substring check (no word-boundary matching, unlike
        # redact()) -- "armed men" is a literal substring of "unarmed men",
        # which would make a report explicitly saying the opposite (no
        # weapon seen) score as a weapon sighting. This test locks that
        # choice in as a regression test, the same class of bug documented
        # in docs/ai-usage.md's Session 1 entry for the redaction layer.
        result = self._extract("Two unarmed men were seen asking neighbours for directions.")
        self.assertNotEqual(result.pattern_id, "weapon_sighting")

    def test_ambient_noise_stays_unclassified(self):
        result = self._extract("Someone's dog was barking loudly all night, quite annoying.")
        self.assertEqual(result.pattern_id, UNCLASSIFIED)


if __name__ == "__main__":
    unittest.main()
