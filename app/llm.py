"""Pluggable model client used by redaction, classification and extraction.

CLAUDE.md specifies Gemini via Vertex AI, with every prompt in a versioned
prompts/ directory. This module defines the interface those three pipeline
stages code against (LLMClient) and two implementations:

- RuleBasedClient: deterministic, dependency-free, config-driven. This is
  the default in this iteration because the sandbox this was built in has
  no package-registry access (see docs/ai-usage.md) -- google-cloud-aiplatform
  cannot be installed or exercised here. It is not a placeholder that
  returns fake data; it does the real work (redaction, channel
  classification, pattern scoring) using the same config files a Gemini
  prompt would be given, so the pipeline is genuinely testable end to end
  today.
- VertexGeminiClient: the production client. Reads prompts/*.md (versioned,
  never inlined, per CLAUDE.md), calls Vertex AI, and is structurally ready
  to drop in once google-cloud-aiplatform is installed and a project is
  configured. It raises clearly at construction time rather than failing
  silently if that dependency is missing.

Swap which one the app uses via AKIYESI_LLM_BACKEND=rule_based|vertex_gemini
(app/pipeline.py reads this once at startup).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Protocol

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class LLMClient(Protocol):
    def redact(self, text: str, terms: Dict[str, List[str]]) -> "RedactionResult":
        ...

    def classify_channel(self, text: str, protected_indicator_terms: List[str]) -> str:
        ...

    def score_patterns(self, text: str, pattern_keywords: Dict[str, List[str]]) -> Dict[str, int]:
        ...


@dataclass(frozen=True)
class RedactionResult:
    redacted_text: str
    categories_redacted: List[str]

    @property
    def was_redacted(self) -> bool:
        return len(self.categories_redacted) > 0


class RuleBasedClient:
    """Deterministic implementation, no network, no third-party deps.

    Phrase matching is whole-phrase, case-insensitive, and replaces a
    matched span with a neutral placeholder rather than deleting it, so
    sentence structure (and therefore the *behaviour* being described)
    survives redaction intact. See prompts/redaction_v1.md for the
    equivalent instruction a Gemini prompt would be given.
    """

    def redact(self, text: str, terms: Dict[str, List[str]]) -> RedactionResult:
        redacted = text
        categories_hit: List[str] = []
        for category, phrases in terms.items():
            category_matched = False
            # Longest phrases first so "Fulani herdsman" matches before "Fulani".
            for phrase in sorted(phrases, key=len, reverse=True):
                # \b...\b: a bare word-boundary match, not substring search --
                # without it, a short entry like "Tiv" false-positive-matches
                # inside "operatives" or "relatives". Caught during seed
                # replay (see docs/ai-usage.md) before this shipped.
                pattern = re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE)
                if pattern.search(redacted):
                    placeholder = "[person]" if category == "stranger_or_foreigner_markers" else "[REDACTED]"
                    redacted = pattern.sub(placeholder, redacted)
                    category_matched = True
            if category_matched:
                categories_hit.append(category)
        # Collapse doubled placeholders / whitespace left behind by
        # substitution so the redacted text reads cleanly.
        redacted = re.sub(r"\s+", " ", redacted).strip()
        redacted = re.sub(r"(\[person\]\s*){2,}", "[person] ", redacted)
        redacted = re.sub(r"(\[REDACTED\]\s*){2,}", "[REDACTED] ", redacted)
        return RedactionResult(redacted_text=redacted, categories_redacted=categories_hit)

    def classify_channel(self, text: str, protected_indicator_terms: List[str]) -> str:
        lowered = text.lower()
        for term in protected_indicator_terms:
            if term.lower() in lowered:
                return "protected"
        return "normal"

    def score_patterns(self, text: str, pattern_keywords: Dict[str, List[str]]) -> Dict[str, int]:
        lowered = text.lower()
        scores: Dict[str, int] = {}
        for pattern_id, keywords in pattern_keywords.items():
            score = 0
            for kw in keywords:
                if kw.lower() in lowered:
                    score += 1
            scores[pattern_id] = score
        return scores


class VertexGeminiClient:
    """Production client -- not exercised in this iteration.

    Construction fails fast and explains why, instead of silently behaving
    like RuleBasedClient, so a misconfigured deployment is loud rather than
    quietly wrong.
    """

    def __init__(self, project_id: str, location: str = "us-central1"):
        try:
            import vertexai  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "VertexGeminiClient requires google-cloud-aiplatform, which is not "
                "installed. Run `pip install -r requirements.txt` on a machine with "
                "network access, then set AKIYESI_LLM_BACKEND=vertex_gemini."
            ) from exc
        self.project_id = project_id
        self.location = location
        self._redaction_prompt = (PROMPTS_DIR / "redaction_v1.md").read_text(encoding="utf-8")
        self._classification_prompt = (PROMPTS_DIR / "classification_v1.md").read_text(encoding="utf-8")
        self._extraction_prompt = (PROMPTS_DIR / "extraction_v1.md").read_text(encoding="utf-8")

    def redact(self, text: str, terms: Dict[str, List[str]]) -> RedactionResult:  # pragma: no cover
        raise NotImplementedError(
            "Wire this up to a Vertex AI call using self._redaction_prompt once "
            "google-cloud-aiplatform is available. RuleBasedClient.redact shows the "
            "exact contract (return value shape) this method must satisfy."
        )

    def classify_channel(self, text: str, protected_indicator_terms: List[str]) -> str:  # pragma: no cover
        raise NotImplementedError("See redact() above -- same pattern, self._classification_prompt.")

    def score_patterns(self, text: str, pattern_keywords: Dict[str, List[str]]) -> Dict[str, int]:  # pragma: no cover
        raise NotImplementedError("See redact() above -- same pattern, self._extraction_prompt.")


def get_llm_client() -> LLMClient:
    import os

    backend = os.environ.get("AKIYESI_LLM_BACKEND", "rule_based")
    if backend == "rule_based":
        return RuleBasedClient()
    if backend == "vertex_gemini":
        project_id = os.environ["AKIYESI_GCP_PROJECT"]
        return VertexGeminiClient(project_id=project_id)
    raise ValueError(f"unknown AKIYESI_LLM_BACKEND: {backend!r}")
