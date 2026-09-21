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
from app.textnorm import fold

_NAME = r"([A-Z][a-z]+(?:\s[A-Z][a-z]+){0,2})"


def _alternation(copulas):
    # Copulas are matched on folded text, so fold them too ("jẹ́" -> "je").
    words = []
    for c in copulas:
        f = fold(c)
        if f not in words:
            words.append(f)
    return "|".join(re.escape(w) for w in words)


def _forward_pattern(copulas):
    # "<Name> is (a/an) <predicate>" / "<Name> je <predicate>"
    return re.compile(r"\b" + _NAME + r"\b\s+(?:" + _alternation(copulas) + r")\s+(?:a\s+|an\s+)?([a-z ]{3,30})")


def _inverted_pattern(copulas):
    # "Ole ni Bello" (yo): the accusation opens the clause, then the name.
    # The whole opening phrase must be the epithet, because "ni" also means
    # "at": "awon ole ni Adeoye street" (robbers at Adeoye street) is an
    # observation, not an accusation, and must not be refused.
    return re.compile(r"(?:^|[.!?,;:]\s*)([A-Za-z]+(?: [a-z]+){0,3})\s+(?:" + _alternation(copulas) + r")\s+" + _NAME + r"\b")


@dataclass(frozen=True)
class TargetingGuardResult:
    blocked: bool
    reason: Optional[str] = None


def check_named_target_accusation(redacted_text: str, locale, config: AppConfig) -> TargetingGuardResult:
    """`locale` is one locale code or a list of them (the message's detected
    locale plus its community's), so a code-switched accusation is caught
    in either language. Matching ignores tone marks (app/textnorm.py)."""
    epithets = [fold(e) for e in config.accusation_terms.epithets_for(locale)]
    mob_terms = [fold(m) for m in config.accusation_terms.mob_language_for(locale)]
    # Case kept (a capital letter is how a name is spotted), marks removed.
    text = fold(redacted_text, lower=False)
    lowered = text.lower()
    forward = _forward_pattern(config.accusation_terms.copulas_for(locale))
    inverted_words = config.accusation_terms.inverted_copulas_for(locale)
    inverted = _inverted_pattern(inverted_words) if inverted_words else None

    def refuse(name, epithet):
        return TargetingGuardResult(
            blocked=True,
            reason=(
                f"Report names a specific individual ('{name}') and makes a character "
                f"accusation ('{epithet}') rather than describing an observed behaviour. "
                "Excluded from clustering to prevent informal targeting; see CLAUDE.md "
                "design rule 1."
            ),
        )

    for match in forward.finditer(text):
        name, predicate = match.group(1), match.group(2).strip().lower()
        for epithet in epithets:
            if predicate.startswith(epithet):
                return refuse(name, epithet)

    if inverted is not None:
        for match in inverted.finditer(text):
            predicate, name = match.group(1).strip().lower(), match.group(2)
            for epithet in epithets:
                if predicate == epithet:
                    return refuse(name, epithet)

    for term in mob_terms:
        if re.search(r"\b" + re.escape(term) + r"\b", lowered):
            name_match = forward.search(text)
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
