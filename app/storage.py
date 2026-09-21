"""Storage layer.

CLAUDE.md specifies Firestore for reports, clusters, audit log and
community config. This iteration uses SQLite (standard library, zero
install) behind the same Store interface a Firestore-backed implementation
would satisfy -- see FirestoreStore at the bottom, which documents the
swap rather than implementing it, since google-cloud-firestore cannot be
installed in the sandbox this was built in (see docs/ai-usage.md).

Clusters are NOT a separate table: they are computed on read from the
`reports` table by app/clustering.py. That keeps "escalated" state as the
only thing that needs writing (to `audit_log`), so there is exactly one
source of truth for what has already been sent to a committee.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from typing import Iterator, List, Optional

from app.models import AuditEntry, InboundLogEntry, Report

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    external_message_id TEXT,
    community_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    sender_hash TEXT NOT NULL,
    redacted_text TEXT NOT NULL,
    categories_redacted TEXT NOT NULL,
    pattern_id TEXT NOT NULL,
    pattern_score INTEGER NOT NULL,
    time_of_day TEXT,
    received_at TEXT NOT NULL,
    status TEXT NOT NULL,
    rejection_reason TEXT,
    locale_detected TEXT
);

CREATE TABLE IF NOT EXISTS inbound_log (
    id TEXT PRIMARY KEY,
    external_message_id TEXT,
    raw_payload TEXT NOT NULL,
    received_at TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    community_id TEXT NOT NULL,
    pattern_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    action TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    evidence_report_ids TEXT NOT NULL,
    referral_brief TEXT NOT NULL,
    profiling_guard_redacted_fraction REAL NOT NULL
);
"""


# What inbound_log.raw_payload holds once a message has been processed. The
# retry log exists only so an unprocessed message is not lost; once the
# report is stored the payload has no further use, so it is not kept.
_SCRUBBED_PAYLOAD = {"scrubbed": True}


class Store:
    """SQLite-backed store. One instance per process/test; thread-safe
    via a lock since the stdlib http.server demo uses a threading server.
    """

    def __init__(self, path: str = ":memory:"):
        self._path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ---- inbound_log (durability for "dropped webhook retried") ----

    def log_inbound(self, entry: InboundLogEntry) -> None:
        row = entry.to_row()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO inbound_log (id, external_message_id, raw_payload, received_at, status, error) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (row["id"], row["external_message_id"], json.dumps(row["raw_payload"]),
                 row["received_at"], row["status"], row["error"]),
            )

    def mark_inbound_status(self, entry_id: str, status: str, error: Optional[str] = None) -> None:
        """Update a log row's status.

        Marking a row 'processed' also replaces its payload with a stub, in the
        same UPDATE, so the original message text is never kept once the
        redacted report is stored. 'received' and 'failed' rows keep the
        payload (already phone-number-free, see app/ingest.py) because a retry
        needs it.
        """
        with self._cursor() as cur:
            if status == "processed":
                cur.execute(
                    "UPDATE inbound_log SET status = ?, error = ?, raw_payload = ? WHERE id = ?",
                    (status, error, json.dumps(_SCRUBBED_PAYLOAD), entry_id),
                )
            else:
                cur.execute(
                    "UPDATE inbound_log SET status = ?, error = ? WHERE id = ?",
                    (status, error, entry_id),
                )

    def pending_inbound(self) -> List[InboundLogEntry]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM inbound_log WHERE status != 'processed' ORDER BY received_at ASC")
            rows = cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["raw_payload"] = json.loads(d["raw_payload"])
            out.append(InboundLogEntry.from_row(d))
        return out

    def find_inbound_by_external_id(self, external_message_id: str) -> Optional[InboundLogEntry]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM inbound_log WHERE external_message_id = ? ORDER BY received_at DESC LIMIT 1",
                (external_message_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["raw_payload"] = json.loads(d["raw_payload"])
        return InboundLogEntry.from_row(d)

    # ---- reports ("the pattern store" -- redacted text only) ----

    def save_report(self, report: Report) -> None:
        row = report.to_row()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO reports (id, external_message_id, community_id, channel, sender_hash, "
                "redacted_text, categories_redacted, pattern_id, pattern_score, time_of_day, "
                "received_at, status, rejection_reason, locale_detected) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["id"], row["external_message_id"], row["community_id"], row["channel"],
                    row["sender_hash"], row["redacted_text"], json.dumps(row["categories_redacted"]),
                    row["pattern_id"], row["pattern_score"], row["time_of_day"], row["received_at"],
                    row["status"], row["rejection_reason"], row["locale_detected"],
                ),
            )

    def find_report_by_external_id(self, external_message_id: str) -> Optional[Report]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM reports WHERE external_message_id = ? LIMIT 1",
                (external_message_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_report(row)

    def reports_for_community(self, community_id: str, channel: Optional[str] = None) -> List[Report]:
        with self._cursor() as cur:
            if channel:
                cur.execute(
                    "SELECT * FROM reports WHERE community_id = ? AND channel = ? ORDER BY received_at ASC",
                    (community_id, channel),
                )
            else:
                cur.execute(
                    "SELECT * FROM reports WHERE community_id = ? ORDER BY received_at ASC",
                    (community_id,),
                )
            rows = cur.fetchall()
        return [self._row_to_report(r) for r in rows]

    def all_reports(self) -> List[Report]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM reports ORDER BY received_at ASC")
            rows = cur.fetchall()
        return [self._row_to_report(r) for r in rows]

    @staticmethod
    def _row_to_report(row: sqlite3.Row) -> Report:
        d = dict(row)
        d["categories_redacted"] = json.loads(d["categories_redacted"])
        return Report.from_row(d)

    # ---- audit log ----

    def save_audit_entry(self, entry: AuditEntry) -> None:
        row = entry.to_row()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log (id, community_id, pattern_id, channel, action, decided_by, "
                "decided_at, evidence_report_ids, referral_brief, profiling_guard_redacted_fraction) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["id"], row["community_id"], row["pattern_id"], row["channel"], row["action"],
                    row["decided_by"], row["decided_at"], json.dumps(row["evidence_report_ids"]),
                    json.dumps(row["referral_brief"]), row["profiling_guard_redacted_fraction"],
                ),
            )

    def audit_log_for_community(self, community_id: str) -> List[AuditEntry]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM audit_log WHERE community_id = ? ORDER BY decided_at DESC",
                (community_id,),
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["evidence_report_ids"] = json.loads(d["evidence_report_ids"])
            d["referral_brief"] = json.loads(d["referral_brief"])
            out.append(AuditEntry.from_row(d))
        return out

    def latest_escalation(self, community_id: str, pattern_id: str) -> Optional[AuditEntry]:
        entries = [
            e for e in self.audit_log_for_community(community_id)
            if e.pattern_id == pattern_id and e.action in ("escalate", "protected_escalate")
        ]
        return entries[0] if entries else None

    def reset_all(self) -> None:
        """Delete every row from every table. Used only by the demo console's
        Reset button (app/demo.py), so a demo can be replayed from a clean
        slate. The schema is untouched.
        """
        with self._cursor() as cur:
            for table in ("reports", "inbound_log", "audit_log"):
                cur.execute(f"DELETE FROM {table}")  # fixed table names, no user input

    def new_id(self) -> str:
        return uuid.uuid4().hex


def make_store(path: str = ":memory:") -> Store:
    return Store(path=path)


# ---------------------------------------------------------------------------
# FirestoreStore -- documented, not implemented.
#
# Not runnable in the sandbox this iteration was built in (no network access
# to install google-cloud-firestore; see docs/ai-usage.md). To deploy for
# real: implement the same method surface as Store above
# (save_report/reports_for_community/save_audit_entry/audit_log_for_community/
# log_inbound/pending_inbound/mark_inbound_status -- which must also drop
# the stored payload when a row is marked 'processed'), backed by three
# collections -- "reports", "audit_log", "inbound_log" -- keyed by the same
# `id` field, with community_id as a top-level field so
# `.where("community_id", "==", ...)` replaces the SQL WHERE clauses above.
# app/pipeline.py and app/server.py depend only on the Store method surface,
# not on SQLite, so this is a drop-in swap once written.
# ---------------------------------------------------------------------------
