"""Corroboration threshold tests (CLAUDE.md "Tests that must pass"):
- Fifteen reports from one hashed sender do not meet the threshold.
- Three reports in one hour do not meet the 3-day span requirement.
Plus the watch (3 senders/3 days) and escalate (5 senders/3 days) rules
from design rule #3, and the protected-channel threshold of 1.
"""
import unittest
from datetime import datetime, timedelta, timezone

from app import clustering
from app.config import get_config
from app.hashing import hash_sender
from app.models import Report

BASE = datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)


def make_report(i, sender_phone, offset, pattern_id="burglary_casing", channel="normal", was_redacted=False):
    return Report(
        id=f"r{i}",
        external_message_id=f"ext-{i}",
        community_id="oke-ado-phase2",
        channel=channel,
        sender_hash=hash_sender(sender_phone),
        redacted_text=f"observation {i}",
        categories_redacted=["stranger_or_foreigner_markers"] if was_redacted else [],
        pattern_id=pattern_id,
        pattern_score=2,
        time_of_day=None,
        received_at=BASE + offset,
        status="stored",
    )


class ClusteringTests(unittest.TestCase):
    def setUp(self):
        self.config = get_config()
        self.community = self.config.community_by_id("oke-ado-phase2")

    def test_fifteen_reports_one_sender_do_not_meet_threshold(self):
        reports = [make_report(i, "+2348010000001", timedelta(days=i)) for i in range(15)]
        clusters = clustering.compute_clusters(reports, self.community)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].distinct_senders, 1)
        self.assertEqual(clusters[0].status, clustering.STATUS_BELOW_THRESHOLD)

    def test_three_reports_in_one_hour_do_not_meet_span_requirement(self):
        reports = [
            make_report(0, "+2348010000001", timedelta(minutes=0)),
            make_report(1, "+2348010000002", timedelta(minutes=20)),
            make_report(2, "+2348010000003", timedelta(minutes=50)),
        ]
        clusters = clustering.compute_clusters(reports, self.community)
        self.assertEqual(len(clusters), 1)
        cluster = clusters[0]
        self.assertEqual(cluster.distinct_senders, 3)
        self.assertLess(cluster.span_days, 3)
        self.assertEqual(cluster.status, clustering.STATUS_BELOW_THRESHOLD)

    def test_three_senders_three_days_reaches_watch_not_escalate(self):
        reports = [
            make_report(0, "+2348010000001", timedelta(days=0)),
            make_report(1, "+2348010000002", timedelta(days=1)),
            make_report(2, "+2348010000003", timedelta(days=3)),
        ]
        clusters = clustering.compute_clusters(reports, self.community)
        self.assertEqual(clusters[0].status, clustering.STATUS_WATCH)

    def test_five_senders_three_days_escalates(self):
        reports = [make_report(i, f"+234801000000{i}", timedelta(days=i)) for i in range(5)]
        clusters = clustering.compute_clusters(reports, self.community)
        self.assertEqual(clusters[0].distinct_senders, 5)
        self.assertEqual(clusters[0].status, clustering.STATUS_ESCALATE_READY)

    def test_protected_channel_threshold_is_one_uncorroborated(self):
        reports = [make_report(0, "+2348010000099", timedelta(days=0), channel="protected")]
        items = clustering.protected_items(reports, self.community)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].status, clustering.PROTECTED_READY)

    def test_unclassified_pattern_never_clusters(self):
        reports = [
            make_report(i, f"+234801000001{i}", timedelta(days=i), pattern_id="unclassified")
            for i in range(6)
        ]
        clusters = clustering.compute_clusters(reports, self.community)
        self.assertEqual(clusters, [])

    def test_already_escalated_cluster_with_no_new_reports_shows_escalated(self):
        reports = [make_report(i, f"+234801000000{i}", timedelta(days=i)) for i in range(5)]
        last_report_at = max(r.received_at for r in reports)
        already = {"burglary_casing": last_report_at + timedelta(hours=1)}
        clusters = clustering.compute_clusters(reports, self.community, already_escalated=already)
        self.assertEqual(clusters[0].status, clustering.STATUS_ESCALATED)

    def test_new_report_after_escalation_reopens_escalate_ready(self):
        reports = [make_report(i, f"+234801000000{i}", timedelta(days=i)) for i in range(5)]
        already = {"burglary_casing": BASE + timedelta(days=2)}  # escalated before the last report arrived
        clusters = clustering.compute_clusters(reports, self.community, already_escalated=already)
        self.assertEqual(clusters[0].status, clustering.STATUS_ESCALATE_READY)


if __name__ == "__main__":
    unittest.main()
