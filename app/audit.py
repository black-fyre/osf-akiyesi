"""Audit trail (CLAUDE.md design rule #6: who decided, on what evidence,
when -- on every escalation).

Thin wrapper around Store.save_audit_entry / audit_log_for_community so
app/server.py and tests have one obvious place to create an escalation
record from a cluster or protected-item decision.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.models import AuditEntry, utcnow
from app.storage import Store


def record_escalation(
    store: Store,
    community_id: str,
    pattern_id: str,
    channel: str,
    action: str,
    decided_by: str,
    evidence_report_ids: List[str],
    referral_brief: Dict[str, Any],
    profiling_guard_redacted_fraction: float,
) -> AuditEntry:
    entry = AuditEntry(
        id=store.new_id(),
        community_id=community_id,
        pattern_id=pattern_id,
        channel=channel,
        action=action,
        decided_by=decided_by,
        decided_at=utcnow(),
        evidence_report_ids=evidence_report_ids,
        referral_brief=referral_brief,
        profiling_guard_redacted_fraction=profiling_guard_redacted_fraction,
    )
    store.save_audit_entry(entry)
    return entry
