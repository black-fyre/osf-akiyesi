"""Extraction (feeds CLAUDE.md component 4, clustering).

Turns a redacted report into: which pattern (if any) it matches, and a
best-effort observed_at time-of-day / location snippet for the referral
brief. Pattern matching is keyword scoring against config/patterns.yaml
(scalability seam #3: "pattern definition is data, not logic") -- a report
that does not clear pattern_min_score against any defined pattern is
UNCLASSIFIED, which is what keeps ambient noise (a noise complaint, a lost
goat, a domestic argument) out of a real pattern's corroboration count.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.config import AppConfig, Community
from app.llm import LLMClient

UNCLASSIFIED = "unclassified"

_TIME_HINTS = [
    (re.compile(r"\b(midnight|late night|2\s?am|3\s?am|after curfew|before dawn)\b", re.I), "night"),
    (re.compile(r"\b(early morning|dawn|sunrise)\b", re.I), "early_morning"),
    (re.compile(r"\b(afternoon)\b", re.I), "afternoon"),
    (re.compile(r"\b(evening|dusk)\b", re.I), "evening"),
]


@dataclass(frozen=True)
class Extraction:
    pattern_id: str
    pattern_score: int
    time_of_day: Optional[str]


def extract(redacted_text: str, community: Community, config: AppConfig, llm: LLMClient, locales=None) -> Extraction:
    # `locales`: the message's detected locale plus its community's, so a
    # Yoruba (or code-switched) message is scored against both word lists.
    locales = locales or [community.locale]
    pattern_keywords = {
        p.id: p.keywords_for(locales) for p in config.patterns
    }
    # Names only when a model reads them; the rule-based client scores on
    # keywords alone and keeps its original two-argument call.
    if getattr(llm, "backend_name", "") == "claude":
        scores = llm.score_patterns(
            redacted_text, pattern_keywords, pattern_names={p.id: p.name for p in config.patterns}
        )
    else:
        scores = llm.score_patterns(redacted_text, pattern_keywords)
    best_pattern, best_score = UNCLASSIFIED, 0
    for pattern_id, score in scores.items():
        if score > best_score:
            best_pattern, best_score = pattern_id, score

    if best_score < config.pattern_min_score:
        best_pattern, best_score = UNCLASSIFIED, 0

    time_of_day = None
    for pattern, label in _TIME_HINTS:
        if pattern.search(redacted_text):
            time_of_day = label
            break

    return Extraction(pattern_id=best_pattern, pattern_score=best_score, time_of_day=time_of_day)
