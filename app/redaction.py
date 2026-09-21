"""Redaction layer (CLAUDE.md design rule #2 -- "the single most important
component").

Strips nationality, ethnicity/tribe, religion, and stranger-or-foreigner
markers from a report's text *before* anything downstream (classification,
extraction, clustering) sees it. This module is the only place in the
codebase allowed to see raw, unredacted report text; app/pipeline.py calls
it first and discards the raw text immediately after, so the identity
content it strips never reaches the report store, let alone the cluster/
pattern store.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from app.config import AppConfig
from app.llm import LLMClient, RedactionResult


@dataclass(frozen=True)
class Redacted:
    text: str
    categories_redacted: List[str]

    @property
    def was_redacted(self) -> bool:
        return len(self.categories_redacted) > 0


def redact_report_text(raw_text: str, locale, config: AppConfig, llm: LLMClient) -> Redacted:
    # `locale`: one code, or a list (detected + community) for code-switched text.
    terms = config.redaction_terms.terms_for(locale)
    result: RedactionResult = llm.redact(raw_text, terms)
    return Redacted(text=result.redacted_text, categories_redacted=result.categories_redacted)
