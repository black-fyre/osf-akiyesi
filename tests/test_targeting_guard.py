"""CLAUDE.md required test:
- A malicious report targeting a named neighbour does not escalate, and
  the refusal reason is retrievable and human-readable.

Exercised end to end through the pipeline (not just the guard function in
isolation) so the test also proves the rejection reason is retrievable
from the stored Report record, not just from an intermediate value that
gets thrown away.
"""
import unittest

from app.config import get_config
from app.llm import RuleBasedClient
from app.storage import make_store
from app.pipeline import process_inbound, STATUS_REJECTED_TARGETING


class TargetingGuardTests(unittest.TestCase):
    def setUp(self):
        self.config = get_config()
        self.llm = RuleBasedClient()
        self.store = make_store(":memory:")

    def test_named_accusation_is_rejected_with_a_human_readable_reason(self):
        payload = {
            "id": "targeting-1",
            "to": "40404*REPORT-OKEADO2",
            "from": "+2348099990001",
            "text": "Chidi Okoro is a thief, everyone should avoid his shop.",
        }
        report = process_inbound(payload, self.config, self.llm, self.store)

        self.assertEqual(report.status, STATUS_REJECTED_TARGETING)
        self.assertIsNotNone(report.rejection_reason)
        self.assertIn("Chidi Okoro", report.rejection_reason)
        self.assertIn("individual", report.rejection_reason.lower())

        # Retrievable later, not just returned once.
        stored = self.store.find_report_by_external_id("targeting-1")
        self.assertIsNotNone(stored)
        self.assertEqual(stored.status, STATUS_REJECTED_TARGETING)
        self.assertEqual(stored.rejection_reason, report.rejection_reason)

    def test_mob_language_is_rejected(self):
        payload = {
            "id": "targeting-2",
            "to": "40404*REPORT-OKEADO2",
            "from": "+2348099990002",
            "text": "Musa Danladi is a criminal and should be dealt with.",
        }
        report = process_inbound(payload, self.config, self.llm, self.store)
        self.assertEqual(report.status, STATUS_REJECTED_TARGETING)
        self.assertIsNotNone(report.rejection_reason)

    def test_rejected_report_never_enters_a_cluster(self):
        from app import clustering

        for i, text in enumerate([
            "Chidi Okoro is a thief, everyone should avoid his shop.",
            "Emeka is a criminal and should be dealt with.",
            "Blessing is a witch, mob justice for her.",
        ]):
            process_inbound(
                {"id": f"reject-cluster-{i}", "to": "40404*REPORT-OKEADO2", "from": f"+234809999{i:04d}", "text": text},
                self.config, self.llm, self.store,
            )
        community = self.config.community_by_id("oke-ado-phase2")
        reports = self.store.reports_for_community("oke-ado-phase2", channel="normal")
        clusters = clustering.compute_clusters(reports, community)
        self.assertEqual(clusters, [])  # three rejected reports, no cluster at all


if __name__ == "__main__":
    unittest.main()
