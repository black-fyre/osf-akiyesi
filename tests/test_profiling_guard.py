"""CLAUDE.md required test:
- Profiling guard fires on a cluster that is 60 percent redacted.
"""
import unittest
from datetime import timedelta

from app import clustering
from app.config import get_config
from tests.test_clustering import make_report, BASE


class ProfilingGuardTests(unittest.TestCase):
    def setUp(self):
        self.config = get_config()
        self.community = self.config.community_by_id("oke-ado-phase2")

    def test_guard_fires_above_60_percent_redacted(self):
        # 4 of 6 redacted = 67%, above the 60% threshold.
        reports = [
            make_report(i, f"+234801000002{i}", timedelta(days=i * 4), was_redacted=(i < 4))
            for i in range(6)
        ]
        clusters = clustering.compute_clusters(reports, self.community)
        cluster = clusters[0]
        self.assertTrue(cluster.profiling.fired)
        self.assertEqual(cluster.status, clustering.STATUS_ESCALATE_BLOCKED_PROFILING)

    def test_guard_does_not_fire_at_or_below_60_percent(self):
        # 3 of 5 redacted = 60%, not *more than* 60%.
        reports = [
            make_report(i, f"+234801000003{i}", timedelta(days=i * 4), was_redacted=(i < 3))
            for i in range(5)
        ]
        clusters = clustering.compute_clusters(reports, self.community)
        cluster = clusters[0]
        self.assertFalse(cluster.profiling.fired)
        self.assertEqual(cluster.status, clustering.STATUS_ESCALATE_READY)

    def test_guard_applies_to_protected_channel_too(self):
        reports = [make_report(0, "+2348010000088", timedelta(days=0), channel="protected", was_redacted=True)]
        items = clustering.protected_items(reports, self.community)
        self.assertEqual(items[0].status, clustering.PROTECTED_BLOCKED_PROFILING)


if __name__ == "__main__":
    unittest.main()
