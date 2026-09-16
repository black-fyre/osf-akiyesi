"""Named-target accusation guard.

Not one of CLAUDE.md's six numbered components, but a direct, testable
consequence of design rule #1 ("intake asks what was observed, never who")
and of the required test "a malicious report targeting a named neighbour
does not escalate, and the refusal reason is retrievable and human
readable". The redaction layer (app/redaction.py) strips *stranger*
identity markers; this guard catches the opposite failure -- a report that
names a specific, known resident and attaches a character judgement to
them rather than describing behaviour. Runs after redaction, before a
report is allowed into clustering.

Heuristic, not a model call, by design: a false negative here just means
the report falls back to needing ordinary multi-sender corroboration
(which a coordinated single-source campaign won't have); a false positive
just means one report needs a human look. Neither failure mode is severe,
which is what makes a cheap heuristic an acceptable choice for a five-day
build.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.config import AppConfig

_NAME_PATTERN = re.compile(
    r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+){0,2})\b\s+(?:is|are)\s+(?:a|an)?\s*([a-z ]{3,30})"
)


@dataclass(frozen=True)
class TargetingGuardResult:
    blocked: bool
    reason: Optional[str] = None


def check_named_target_accusation(redacted_text: str, locale: str, config: AppConfig) -> TargetingGuardResult:
    epithets = [e.lower() for e in config.accusation_terms.epithets_for(locale)]
    mob_terms = [m.lower() for m in config.accusation_terms.mob_language_for(locale)]
    lowered = redacted_text.lower()

    for match in _NAME_PATTERN.finditer(redacted_text):
        name, predicate = match.group(1), match.group(2).strip().lower()
        for epithet in epithets:
            if predicate.startswith(epithet):
                return TargetingGuardResult(
                    blocked=True,
                    reason=(
                        f"Report names a specific individual ('{name}') and makes a character "
                        f"accusation ('{epithet}') rather than describing an observed behaviour. "
                        "Excluded from clustering to prevent informal targeting; see CLAUDE.md "
                        "design rule 1."
                    ),
                )

    for term in mob_terms:
        if term in lowered:
            name_match = _NAME_PATTERN.search(redacted_text)
            who = f" ('{name_match.group(1)}')" if name_match else ""
            return TargetingGuardResult(
                blocked=True,
                reason=(
                    f"Report contains mob-justice language{who} ('{term}') rather than an "
                    "observation for the security committee to corroborate. Excluded from "
                    "clustering."
                ),
            )

    return TargetingGuardResult(blocked=False)
