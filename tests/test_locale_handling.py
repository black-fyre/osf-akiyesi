"""CLAUDE.md required test:
- A non-English report is handled or fails loudly, never silently
  discarded.
"""
import unittest

from app.config import get_config
from app.llm import RuleBasedClient
from app.storage import make_store
from app.pipeline import process_inbound, STATUS_NEEDS_REVIEW_LOCALE, STATUS_STORED


class LocaleHandlingTests(unittest.TestCase):
    def setUp(self):
        self.config = get_config()
        self.llm = RuleBasedClient()
        self.store = make_store(":memory:")

    def test_unsupported_locale_is_stored_for_review_not_discarded(self):
        payload = {
            "id": "locale-1",
            "to": "40404*REPORT-OKEADO2",
            "from": "+2348077770001",
            "text": "Des hommes déchargeaient des sacs dans la maison vide la nuit.",
            "locale": "fr",
        }
        report = process_inbound(payload, self.config, self.llm, self.store)

        # Not discarded: it is stored, with a status and reason a human can act on.
        self.assertEqual(report.status, STATUS_NEEDS_REVIEW_LOCALE)
        self.assertIn("fr", report.rejection_reason)
        self.assertIsNotNone(self.store.find_report_by_external_id("locale-1"))

        # And excluded from clustering until reviewed.
        from app import clustering
        community = self.config.community_by_id("oke-ado-phase2")
        reports = self.store.reports_for_community("oke-ado-phase2", channel="normal")
        clusters = clustering.compute_clusters(reports, community)
        self.assertEqual(clusters, [])

    def test_yoruba_stub_locale_is_accepted(self):
        payload = {
            "id": "locale-2",
            "to": "40404*REPORT-OKEADO2",
            "from": "+2348077770002",
            "text": "Won n wo ile wa ni oru.",
            "locale": "yo",
        }
        report = process_inbound(payload, self.config, self.llm, self.store)
        self.assertEqual(report.status, STATUS_STORED)

    def test_no_locale_hint_defaults_to_community_locale(self):
        payload = {
            "id": "locale-3",
            "to": "40404*REPORT-OKEADO2",
            "from": "+2348077770003",
            "text": "Someone was checking gates along the street.",
        }
        report = process_inbound(payload, self.config, self.llm, self.store)
        self.assertEqual(report.status, STATUS_STORED)
        self.assertEqual(report.locale_detected, "en-NG")


if __name__ == "__main__":
    unittest.main()
