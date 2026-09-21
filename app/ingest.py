"""Ingest: SMS webhook + simulated inbound (CLAUDE.md component 1).

Design rule: a dropped webhook is retried, not silently lost. Every inbound
payload is durably logged (inbound_log, status='received') *before*
pipeline processing starts. If processing raises, the log entry is marked
'failed' with the error, and retry_pending() can reprocess it later --
process_inbound()'s dedup-by-external_message_id check makes reprocessing
an already-saved report a no-op, so retrying is always safe.

Privacy (design rule #7, anonymity by default): the log exists only so a
dropped message can be retried, so it holds as little as that needs.
  - The sender's phone number is replaced by its salted hash before the
    payload is logged, so the number is never written to storage at all.
  - The original message text is kept only while a message is still
    waiting to be processed (status 'received' or 'failed'). The moment it
    is marked 'processed' the payload is scrubbed (see
    Store.mark_inbound_status), leaving only the redacted text in `reports`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.config import AppConfig
from app.hashing import hash_sender
from app.llm import LLMClient
from app.models import InboundLogEntry, Report, utcnow
from app.pipeline import process_inbound
from app.storage import Store


# Payload keys that can carry the sender's phone number (see app/pipeline.py
# parse_payload for the same aliases).
_PHONE_KEYS = ("from", "sender")


def _without_phone_number(raw_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Copy of the payload with the phone number replaced by its salted hash.

    The hash is what the pipeline needs (corroboration counts distinct
    senders); the number itself has no further use, so it is dropped here,
    before anything is written to storage. This does not change who can post
    to the webhook: signature verification is still listed as not yet built.
    """
    safe = dict(raw_payload)
    phone = None
    for key in _PHONE_KEYS:
        value = safe.pop(key, None)
        phone = phone or value
    if phone and not safe.get("sender_hash"):
        safe["sender_hash"] = hash_sender(str(phone))
    return safe


def receive_webhook(raw_payload: Dict[str, Any], config: AppConfig, llm: LLMClient, store: Store) -> Optional[Report]:
    payload = _without_phone_number(raw_payload)
    entry = InboundLogEntry(
        id=store.new_id(),
        external_message_id=payload.get("id"),
        raw_payload=payload,
        received_at=utcnow(),
        status="received",
    )
    store.log_inbound(entry)

    try:
        report = process_inbound(payload, config, llm, store)
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: log, never crash the webhook
        store.mark_inbound_status(entry.id, "failed", error=str(exc))
        return None

    store.mark_inbound_status(entry.id, "processed")
    return report


def retry_pending(config: AppConfig, llm: LLMClient, store: Store) -> List[Report]:
    """Reprocess every inbound_log row that never reached 'processed'.

    Safe to call repeatedly / on a schedule: process_inbound is idempotent
    per external_message_id, so a row that actually succeeded but was never
    marked (a crash between save_report and mark_inbound_status) is not
    double-stored, just re-marked processed.
    """
    recovered: List[Report] = []
    for entry in store.pending_inbound():
        try:
            report = process_inbound(entry.raw_payload, config, llm, store)
            store.mark_inbound_status(entry.id, "processed")
            recovered.append(report)
        except Exception as exc:  # noqa: BLE001
            store.mark_inbound_status(entry.id, "failed", error=str(exc))
    return recovered
