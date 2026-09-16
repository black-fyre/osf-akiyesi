"""CLAUDE.md required test:
- A dropped webhook is retried, not silently lost.
"""
import unittest
from unittest.mock import patch

from app.config import get_config
from app.llm import RuleBasedClient
from app.storage import make_store
from app import ingest


PAYLOAD = {
    "id": "dropped-1",
    "to": "40404*REPORT-OKEADO2",
    "from": "+2348088880001",
    "text": "Someone was checking gates along Alade Street late last night.",
}


class IngestRetryTests(unittest.TestCase):
    def setUp(self):
        self.config = get_config()
        self.llm = RuleBasedClient()
        self.store = make_store(":memory:")

    def test_a_processing_crash_is_logged_not_lost_and_retry_recovers_it(self):
        real_process_inbound = ingest.process_inbound

        # Simulate the webhook handler crashing partway through processing
        # (a downstream call throws) on the *first* attempt only.
        call_count = {"n": 0}

        def flaky(raw_payload, config, llm, store):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated crash mid-processing")
            return real_process_inbound(raw_payload, config, llm, store)

        with patch("app.ingest.process_inbound", side_effect=flaky):
            report = ingest.receive_webhook(PAYLOAD, self.config, self.llm, self.store)

        # The webhook call itself did not crash the caller, and did not
        # produce a report yet...
        self.assertIsNone(report)

        # ...but the raw payload was durably logged before processing was
        # attempted, so it is retrievable, not silently lost.
        pending = self.store.pending_inbound()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].status, "failed")
        self.assertIn("simulated crash", pending[0].error)
        self.assertEqual(pending[0].raw_payload["id"], "dropped-1")

        # A retry (e.g. a cron calling ingest.retry_pending) recovers it.
        recovered = ingest.retry_pending(self.config, self.llm, self.store)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].external_message_id, "dropped-1")
        self.assertEqual(self.store.pending_inbound(), [])

        # And retrying again is a safe no-op (idempotent), not a duplicate.
        again = ingest.retry_pending(self.config, self.llm, self.store)
        self.assertEqual(again, [])
        all_reports = [r for r in self.store.all_reports() if r.external_message_id == "dropped-1"]
        self.assertEqual(len(all_reports), 1)

    def test_unknown_inbound_identifier_is_logged_not_silently_lost(self):
        bad_payload = dict(PAYLOAD, id="unknown-inbound-1", to="40404*DOES-NOT-EXIST")
        report = ingest.receive_webhook(bad_payload, self.config, self.llm, self.store)
        self.assertIsNone(report)
        pending = self.store.pending_inbound()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].status, "failed")
        self.assertIn("no community configured", pending[0].error)


if __name__ == "__main__":
    unittest.main()
