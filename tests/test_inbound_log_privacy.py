"""Privacy regression tests for the durable inbound log (design rule #7:
anonymity by default).

The inbound log exists so a dropped webhook can be retried, not silently
lost. An earlier version kept every raw payload forever, which meant the
sender's phone number and the original, unredacted message text sat in the
database indefinitely, contradicting "only the redacted text is ever
persisted". These tests pin the fix:

- the phone number is never written to storage (only its salted hash is);
- the original message text survives only while a message is unprocessed
  and is scrubbed the moment it is processed;
- error messages stored for failed rows never echo the payload.
"""
import unittest
from unittest.mock import patch

from app import ingest
from app.config import get_config
from app.hashing import hash_sender
from app.llm import RuleBasedClient
from app.pipeline import MissingFieldError, parse_payload, process_inbound
from app.storage import make_store

PHONE = "+2348055550123"
PHONE_NO_PLUS = "2348055550123"
PHONE_LOCAL = "08055550123"
IDENTITY_TERM = "Fulani"
TEXT = f"A {IDENTITY_TERM} man was seen checking gates along Alade Street."


def payload(**overrides):
    base = {"id": "priv-1", "to": "40404*REPORT-OKEADO2", "from": PHONE, "text": TEXT}
    base.update(overrides)
    return base


def database_dump(store) -> str:
    """Every table, every row, as SQL text: if a value is stored, it is in here."""
    with store._lock:
        return "\n".join(store._conn.iterdump())


class InboundLogPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.config = get_config()
        self.llm = RuleBasedClient()
        self.store = make_store(":memory:")

    def assert_no_phone_number(self, dump):
        for form in (PHONE, PHONE_NO_PLUS, PHONE_LOCAL):
            self.assertNotIn(form, dump)

    def test_processed_message_leaves_no_phone_number_or_original_text_in_storage(self):
        report = ingest.receive_webhook(payload(), self.config, self.llm, self.store)
        self.assertIsNotNone(report)

        dump = database_dump(self.store)
        self.assert_no_phone_number(dump)
        # The identity term was redacted before the report was stored, and the
        # log's copy of the original text was scrubbed once it was processed.
        self.assertNotIn(IDENTITY_TERM, dump)
        # Sanity: what *is* kept is the hash and the redacted behaviour.
        self.assertIn(hash_sender(PHONE), dump)
        self.assertIn("checking gates", report.redacted_text)

    def test_processed_log_row_is_scrubbed_not_deleted(self):
        ingest.receive_webhook(payload(), self.config, self.llm, self.store)
        with self.store._lock:
            rows = self.store._conn.execute(
                "SELECT status, raw_payload, external_message_id FROM inbound_log"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "processed")
        self.assertEqual(rows[0]["raw_payload"], '{"scrubbed": true}')
        # Still auditable that the message arrived and was handled.
        self.assertEqual(rows[0]["external_message_id"], "priv-1")

    def test_failed_message_keeps_its_text_for_retry_but_never_the_phone_number(self):
        real = ingest.process_inbound
        calls = {"n": 0}

        def flaky(raw, config, llm, store):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated crash mid-processing")
            return real(raw, config, llm, store)

        with patch("app.ingest.process_inbound", side_effect=flaky):
            self.assertIsNone(ingest.receive_webhook(payload(), self.config, self.llm, self.store))

        # Still waiting to be retried, so the text has to be kept...
        pending = self.store.pending_inbound()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].raw_payload["text"], TEXT)
        # ...but the phone number never is, even here.
        self.assert_no_phone_number(database_dump(self.store))
        self.assertEqual(pending[0].raw_payload["sender_hash"], hash_sender(PHONE))

        # Once the retry succeeds, the text is scrubbed like any processed row.
        recovered = ingest.retry_pending(self.config, self.llm, self.store)
        self.assertEqual(len(recovered), 1)
        dump = database_dump(self.store)
        self.assert_no_phone_number(dump)
        self.assertNotIn(IDENTITY_TERM, dump)
        self.assertEqual(self.store.pending_inbound(), [])

    def test_sender_hash_is_identical_whether_hashed_at_the_door_or_in_the_pipeline(self):
        # Retried messages arrive already hashed; direct calls (tests, seed
        # replay) arrive with the number. Both must give the same sender, or
        # corroboration would count one person twice.
        via_webhook = ingest.receive_webhook(payload(id="a"), self.config, self.llm, self.store)
        direct = process_inbound(payload(id="b"), self.config, self.llm, self.store)
        self.assertEqual(via_webhook.sender_hash, direct.sender_hash)
        self.assertEqual(via_webhook.sender_hash, hash_sender(PHONE))

    def test_error_messages_do_not_echo_the_payload(self):
        with self.assertRaises(MissingFieldError) as ctx:
            parse_payload(payload(text=""))
        message = str(ctx.exception)
        self.assertIn("text", message)  # says which field is missing
        self.assert_no_phone_number(message)
        self.assertNotIn("Alade", message)

        # And what a failed row stores in its error column is equally clean.
        self.assertIsNone(ingest.receive_webhook(payload(id="bad", text=""), self.config, self.llm, self.store))
        pending = self.store.pending_inbound()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].status, "failed")
        self.assert_no_phone_number(pending[0].error)


if __name__ == "__main__":
    unittest.main()
