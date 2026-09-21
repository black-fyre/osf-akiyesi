"""Clustering with a corroboration threshold (CLAUDE.md component 4).

"This is not a reporting tool. It is an aggregation tool." One report is
nothing; many weak reports of the same behaviour, from different people,
over several days, is a pattern. This module turns the flat report table
into per-(community, pattern) cluster summaries and applies the threshold
config (app/config.py Thresholds) plus the profiling guard
(app/profiling_guard.py) to decide whether a cluster is below threshold,
a watch, ready to escalate, or blocked pending profiling review.

Never escalate on one report (design rule #3) -- except the protected
channel, where a whistleblower is by definition alone, and threshold is 1
by config, not by a special case here: protected reports are handled by
protected_escalations() below using the exact same profiling-guard call,
just without the distinct-sender/span gate.

A pattern can also carry its own, lower watch/escalate bar instead of the
community default (PatternDefinition.watch_override/escalate_override in
config/patterns.yaml, e.g. weapon_sighting) -- still config, not a special
case, and design rule #3 still holds: the lowest any pattern's escalate
threshold is allowed to go is a matter of what's written in
config/patterns.yaml, but it is never 1. A single high-signal report only
ever reaches STATUS_WATCH (visible, prioritised on the desk), never
STATUS_ESCALATE_READY.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from app.config import AppConfig, Community, PatternDefinition
from app.models import Report
from app.profiling_guard import ProfilingGuardResult, check_profiling_cascade

STATUS_BELOW_THRESHOLD = "below_threshold"
STATUS_WATCH = "watch"
STATUS_ESCALATE_READY = "escalate_ready"
STATUS_ESCALATE_BLOCKED_PROFILING = "escalate_blocked_profiling"
STATUS_ESCALATED = "escalated"

PROTECTED_READY = "protected_ready"
PROTECTED_BLOCKED_PROFILING = "protected_blocked_profiling"
PROTECTED_ESCALATED = "protected_escalated"


@dataclass
class ClusterSummary:
    community_id: str
    pattern_id: str
    report_ids: List[str]
    distinct_senders: int
    span_days: float
    first_report_at: datetime
    last_report_at: datetime
    status: str
    profiling: ProfilingGuardResult
    already_escalated_at: Optional[datetime] = None
    # True when this pattern is marked high_signal in config/patterns.yaml
    # (e.g. weapon_sighting) -- drives the desk UI's priority badge. Purely
    # descriptive: it does not change `status` or the threshold math below,
    # which is driven by the pattern's watch_override/escalate_override.
    high_signal: bool = False


@dataclass
class ProtectedItem:
    report: Report
    status: str
    profiling: ProfilingGuardResult
    already_escalated_at: Optional[datetime] = None


def _span_days(reports: List[Report]) -> float:
    if len(reports) < 2:
        return 0.0
    times = [r.received_at for r in reports]
    return (max(times) - min(times)).total_seconds() / 86400.0


def resolve_thresholds(community: Community, pattern_def: Optional[PatternDefinition]):
    """The (watch, escalate) SpanThresholds that apply to one pattern in one
    community: the pattern's own override when config/patterns.yaml sets one,
    otherwise the community default. One function, so the desk logic below
    and anything that displays the bar (the demo console) can never disagree
    about what the bar is.
    """
    default = community.thresholds.normal_channel
    watch = (pattern_def.watch_override if pattern_def else None) or default.watch
    escalate = (pattern_def.escalate_override if pattern_def else None) or default.escalate
    return watch, escalate


def compute_clusters(
    reports: List[Report],
    community: Community,
    already_escalated: Optional[Dict[str, datetime]] = None,
    patterns: Optional[List[PatternDefinition]] = None,
) -> List[ClusterSummary]:
    """already_escalated maps pattern_id -> decided_at of the most recent
    escalation for this community+pattern, so a cluster that has already
    been sent to the committee (with no new reports since) shows as
    STATUS_ESCALATED instead of re-offering escalate_ready.

    patterns (optional, config.patterns): looked up per pattern_id so a
    pattern can carry its own watch/escalate thresholds
    (PatternDefinition.watch_override/escalate_override) instead of
    inheriting community.thresholds.normal_channel uniformly -- e.g.
    weapon_sighting escalates at 2 senders/1 day instead of the community
    default. Omitting this parameter (existing callers, existing tests)
    keeps every pattern on the community default, unchanged from before --
    this parameter is additive and backward compatible by construction.
    """
    already_escalated = already_escalated or {}
    patterns_by_id = {p.id: p for p in (patterns or [])}

    by_pattern: Dict[str, List[Report]] = {}
    for r in reports:
        if r.channel != "normal" or r.status != "stored" or r.pattern_id == "unclassified":
            continue
        by_pattern.setdefault(r.pattern_id, []).append(r)

    summaries: List[ClusterSummary] = []
    for pattern_id, group in by_pattern.items():
        pattern_def = patterns_by_id.get(pattern_id)
        watch_threshold, escalate_threshold = resolve_thresholds(community, pattern_def)
        high_signal = bool(pattern_def.high_signal) if pattern_def else False

        distinct_senders = len({r.sender_hash for r in group})
        span = _span_days(group)
        profiling = check_profiling_cascade(
            [r.was_redacted for r in group],
            community.thresholds.profiling_guard_max_redacted_fraction,
        )

        meets_watch = (
            distinct_senders >= watch_threshold.min_distinct_senders and span >= watch_threshold.min_span_days
        )
        meets_escalate = (
            distinct_senders >= escalate_threshold.min_distinct_senders
            and span >= escalate_threshold.min_span_days
        )

        last_escalated_at = already_escalated.get(pattern_id)
        last_report_at = max(r.received_at for r in group)

        if meets_escalate:
            if last_escalated_at is not None and last_escalated_at >= last_report_at:
                status = STATUS_ESCALATED
            elif profiling.fired:
                status = STATUS_ESCALATE_BLOCKED_PROFILING
            else:
                status = STATUS_ESCALATE_READY
        elif meets_watch:
            status = STATUS_WATCH
        else:
            status = STATUS_BELOW_THRESHOLD

        summaries.append(
            ClusterSummary(
                community_id=community.id,
                pattern_id=pattern_id,
                report_ids=[r.id for r in group],
                distinct_senders=distinct_senders,
                span_days=span,
                first_report_at=min(r.received_at for r in group),
                last_report_at=last_report_at,
                status=status,
                profiling=profiling,
                already_escalated_at=last_escalated_at,
                high_signal=high_signal,
            )
        )

    summaries.sort(key=lambda s: s.last_report_at, reverse=True)
    return summaries


def protected_items(
    reports: List[Report],
    community: Community,
    already_escalated_report_ids: Optional[Dict[str, datetime]] = None,
) -> List[ProtectedItem]:
    already_escalated_report_ids = already_escalated_report_ids or {}
    threshold = community.thresholds.protected_channel
    items: List[ProtectedItem] = []
    for r in reports:
        if r.channel != "protected" or r.status != "stored":
            continue
        # threshold.min_distinct_senders is 1 by config -- a single report
        # already qualifies; span requirement is 0 for the same reason.
        meets = 1 >= threshold.min_distinct_senders
        profiling = check_profiling_cascade([r.was_redacted], community.thresholds.profiling_guard_max_redacted_fraction)
        escalated_at = already_escalated_report_ids.get(r.id)
        if not meets:
            continue
        if escalated_at is not None:
            status = PROTECTED_ESCALATED
        elif profiling.fired:
            status = PROTECTED_BLOCKED_PROFILING
        else:
            status = PROTECTED_READY
        items.append(ProtectedItem(report=r, status=status, profiling=profiling, already_escalated_at=escalated_at))
    items.sort(key=lambda i: i.report.received_at, reverse=True)
    return items
