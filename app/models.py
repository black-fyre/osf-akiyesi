"""Shared record types persisted by app/storage.py.

Kept as plain dataclasses (not pydantic models) for the same reason as
app/config.py: this iteration is standard-library only. to_dict/from_dict
on each type is what storage.py uses to (de)serialise into SQLite.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

ISO = "%Y-%m-%dT%H:%M:%S.%f%z"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_str(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _str_to_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


@dataclass
class Report:
    id: str
    external_message_id: Optional[str]
    community_id: str
    channel: str  # "normal" | "protected"
    sender_hash: str
    redacted_text: str
    categories_redacted: List[str]
    pattern_id: str
    pattern_score: int
    time_of_day: Optional[str]
    received_at: datetime
    status: str  # "stored" | "rejected_targeting" | "needs_review_locale"
    rejection_reason: Optional[str] = None
    locale_detected: Optional[str] = None

    @property
    def was_redacted(self) -> bool:
        return len(self.categories_redacted) > 0

    def to_row(self) -> Dict[str, Any]:
        d = asdict(self)
        d["categories_redacted"] = list(self.categories_redacted)
        d["received_at"] = _dt_to_str(self.received_at)
        return d

    @classmethod
    def from_row(cls, d: Dict[str, Any]) -> "Report":
        d = dict(d)
        d["received_at"] = _str_to_dt(d["received_at"])
        return cls(**d)


@dataclass
class InboundLogEntry:
    id: str
    external_message_id: Optional[str]
    raw_payload: Dict[str, Any]
    received_at: datetime
    status: str  # "received" | "processed" | "failed"
    error: Optional[str] = None

    def to_row(self) -> Dict[str, Any]:
        d = asdict(self)
        d["received_at"] = _dt_to_str(self.received_at)
        return d

    @classmethod
    def from_row(cls, d: Dict[str, Any]) -> "InboundLogEntry":
        d = dict(d)
        d["received_at"] = _str_to_dt(d["received_at"])
        return cls(**d)


@dataclass
class AuditEntry:
    id: str
    community_id: str
    pattern_id: str
    channel: str  # "normal" | "protected"
    action: str  # "escalate" | "protected_escalate" | "profiling_review_required"
    decided_by: str
    decided_at: datetime
    evidence_report_ids: List[str]
    referral_brief: Dict[str, Any]
    profiling_guard_redacted_fraction: float

    def to_row(self) -> Dict[str, Any]:
        d = asdict(self)
        d["decided_at"] = _dt_to_str(self.decided_at)
        return d

    @classmethod
    def from_row(cls, d: Dict[str, Any]) -> "AuditEntry":
        d = dict(d)
        d["decided_at"] = _str_to_dt(d["decided_at"])
        return cls(**d)
