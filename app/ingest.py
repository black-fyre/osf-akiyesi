"""Ingest: SMS webhook + simulated inbound (CLAUDE.md component 1).

Design rule: a dropped webhook is retried, not silently lost. Every inbound
payload is durably logged (inbound_log, status='received') *before*
pipeline processing starts. If processing raises, the log entry is marked
'failed' with the error, and retry_pending() can reprocess it later --
process_inbound()'s dedup-by-external_message_id check makes reprocessing
an already-saved report a no-op, so retrying is always safe.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.config import AppConfig
from app.llm import LLMClient
from app.models import InboundLogEntry, Report, utcnow
from app.pipeline import process_inbound
from app.storage import Store


def receive_webhook(raw_payload: Dict[str, Any], config: AppConfig, llm: LLMClient, store: Store) -> Optional[Report]:
    entry = InboundLogEntry(
        id=store.new_id(),
        external_message_id=raw_payload.get("id"),
        raw_payload=raw_payload,
        received_at=utcnow(),
        status="received",
    )
    store.log_inbound(entry)

    try:
        report = process_inbound(raw_payload, config, llm, store)
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
