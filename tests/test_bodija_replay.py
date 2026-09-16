"""CLAUDE.md required test:
- Bodija replay: seeded weak signals cross the threshold before the
  seeded incident.

seed/bodija_scale_replay.json carries six explosives_storage-pattern
reports dated in the six weeks before 16 January 2024 (the real Bodija
explosives incident), reusing the bodija-close-9 community to prove the
same pipeline generalises to a different pattern definition (CLAUDE.md
scalability seam #3). This test feeds them through in chronological order
and asserts the corroboration threshold (both "watch" and "escalate")
would have been crossed before the incident date, using only reports that
predate it.
"""
import json
import unittest
from datetime import datetime
from pathlib import Path

from app import clustering
from app.config import get_config
from app.llm import RuleBasedClient
from app.storage import make_store
from app.pipeline import process_inbound

SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "bodija_scale_replay.json"


class BodijaReplayTests(unittest.TestCase):
    def setUp(self):
        self.config = get_config()
        self.llm = RuleBasedClient()
        self.store = make_store(":memory:")
        raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        self.incident_date = None
        self.payloads = []
        for row in raw:
            if row.get("_note"):
                self.incident_date = datetime.fromisoformat(row["_incident_date"])
            else:
                self.payloads.append(row)
        self.payloads.sort(key=lambda r: r["date"])

    def test_all_seed_reports_predate_the_incident(self):
        self.assertIsNotNone(self.incident_date)
        for p in self.payloads:
            self.assertLess(datetime.fromisoformat(p["date"]), self.incident_date)

    def test_threshold_crossed_before_incident_date(self):
        community = self.config.community_by_id("bodija-close-9")
        first_watch_at = None
        first_escalate_at = None

        for payload in self.payloads:
            process_inbound(payload, self.config, self.llm, self.store)
            reports = self.store.reports_for_community("bodija-close-9", channel="normal")
            clusters = clustering.compute_clusters(reports, community)
            match = next((c for c in clusters if c.pattern_id == "explosives_storage"), None)
            if match is None:
                continue
            if first_watch_at is None and match.status in (
                clustering.STATUS_WATCH, clustering.STATUS_ESCALATE_READY, clustering.STATUS_ESCALATE_BLOCKED_PROFILING
            ):
                first_watch_at = match.last_report_at
            if first_escalate_at is None and match.status in (
                clustering.STATUS_ESCALATE_READY, clustering.STATUS_ESCALATE_BLOCKED_PROFILING
            ):
                first_escalate_at = match.last_report_at

        self.assertIsNotNone(first_watch_at, "seeded signals never reached a watch")
        self.assertIsNotNone(first_escalate_at, "seeded signals never reached escalate")
        self.assertLess(first_watch_at, self.incident_date)
        self.assertLess(first_escalate_at, self.incident_date)

        days_before_incident = (self.incident_date - first_escalate_at).days
        self.assertGreaterEqual(
            days_before_incident, 1,
            "the point is that this would have been actionable before the incident, not on the day of it",
        )


if __name__ == "__main__":
    unittest.main()
