"""Referral brief generation (the "government bridge", CLAUDE.md).

Amotekun is a state government security outfit, so every escalation --
normal-channel or protected -- produces a structured brief a committee
(or the landlord association) can hand to it: observation summary,
corroboration count, time window, location (the community), redaction
record.

Timestamps in the brief are deliberately DATE-ONLY (design rule #4: "Do not
show timestamps finer than daily granularity in the desk view" -- enforced
here, at brief-generation time, rather than only in a template, so no
finer-grained time can leak through any rendering of this data,
HTML or JSON).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.clustering import ClusterSummary, ProtectedItem
from app.config import Community
from app.models import Report


def _date_only(dt) -> str:
    return dt.date().isoformat()


def build_cluster_referral_brief(cluster: ClusterSummary, reports: List[Report], community: Community) -> Dict[str, Any]:
    observations = [r.redacted_text for r in reports if r.id in cluster.report_ids]
    redaction_record = {
        "reports_redacted": sum(1 for r in reports if r.id in cluster.report_ids and r.was_redacted),
        "reports_total": len(cluster.report_ids),
        "redacted_fraction": round(cluster.profiling.redacted_fraction, 2),
        "categories_seen": sorted({c for r in reports if r.id in cluster.report_ids for c in r.categories_redacted}),
    }
    return {
        "kind": "normal_cluster",
        "community": community.name,
        "pattern_id": cluster.pattern_id,
        "observation_summary": observations,
        "corroboration": {
            "distinct_senders": cluster.distinct_senders,
            "report_count": len(cluster.report_ids),
        },
        "time_window": {
            "from": _date_only(cluster.first_report_at),
            "to": _date_only(cluster.last_report_at),
        },
        "location": community.name,
        "redaction_record": redaction_record,
    }


def build_protected_referral_brief(item: ProtectedItem, community: Community) -> Dict[str, Any]:
    r = item.report
    return {
        "kind": "protected_report",
        "community": community.name,
        "pattern_id": r.pattern_id,
        "observation_summary": [r.redacted_text],
        "corroboration": {
            "distinct_senders": 1,
            "report_count": 1,
            "label": "uncorroborated",
        },
        "time_window": {
            "from": _date_only(r.received_at),
            "to": _date_only(r.received_at),
        },
        "location": community.name,
        "redaction_record": {
            "reports_redacted": 1 if r.was_redacted else 0,
            "reports_total": 1,
            "redacted_fraction": 1.0 if r.was_redacted else 0.0,
            "categories_seen": sorted(r.categories_redacted),
        },
    }
