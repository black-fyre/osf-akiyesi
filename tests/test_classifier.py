"""Channel classifier: inbound-identifier routing plus the content
fallback (CLAUDE.md component 3)."""
import unittest

from app.config import get_config
from app.llm import RuleBasedClient
from app.classifier import classify_channel


class ClassifierTests(unittest.TestCase):
    def setUp(self):
        self.config = get_config()
        self.llm = RuleBasedClient()
        self.community = self.config.community_by_id("oke-ado-phase2")

    def test_protected_inbound_identifier_always_wins(self):
        channel = classify_channel(
            "40404*SAFE-OKEADO2", "just a normal observation with no indicator words", self.community, self.config, self.llm
        )
        self.assertEqual(channel, "protected")

    def test_normal_inbound_with_ordinary_text_is_normal(self):
        channel = classify_channel(
            "40404*REPORT-OKEADO2", "Two men were photographing the houses from a parked car.", self.community, self.config, self.llm
        )
        self.assertEqual(channel, "normal")

    def test_normal_inbound_but_content_about_security_apparatus_is_protected(self):
        channel = classify_channel(
            "40404*REPORT-OKEADO2",
            "The gateman is asking for a bribe before he lets visitors in.",
            self.community, self.config, self.llm,
        )
        self.assertEqual(channel, "protected")


if __name__ == "__main__":
    unittest.main()
