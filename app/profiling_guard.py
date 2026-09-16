"""Profiling guard (CLAUDE.md design rule #5).

A curfew makes "stranger seen out after curfew" the single most common
report shape -- and that is exactly the shape that becomes profiling. If
more than max_redacted_fraction of a cluster's reports needed identity-
content redaction, the cluster is suspicion about a person, not observation
of behaviour. Flag it and require manual review before it can escalate,
even if it has cleared the ordinary corroboration threshold.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class ProfilingGuardResult:
    fired: bool
    redacted_fraction: float
    threshold: float


def check_profiling_cascade(was_redacted_flags: Sequence[bool], max_redacted_fraction: float) -> ProfilingGuardResult:
    if not was_redacted_flags:
        return ProfilingGuardResult(fired=False, redacted_fraction=0.0, threshold=max_redacted_fraction)
    fraction = sum(1 for f in was_redacted_flags if f) / len(was_redacted_flags)
    return ProfilingGuardResult(
        fired=fraction > max_redacted_fraction,
        redacted_fraction=fraction,
        threshold=max_redacted_fraction,
    )
