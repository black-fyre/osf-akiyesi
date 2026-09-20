"""Pluggable model client used by redaction, classification and extraction.

CLAUDE.md specifies Gemini via Vertex AI, with every prompt in a versioned
prompts/ directory. This module defines the interface those three pipeline
stages code against (LLMClient) and two implementations:

- RuleBasedClient: deterministic, dependency-free, config-driven. This is
  the default backend (AKIYESI_LLM_BACKEND=rule_based) and what the demo
  and full test suite actually run, because the sandbox this was built in
  has no route to any model-provider API (see docs/ai-usage.md). It is not
  a placeholder that returns fake data; it does the real work (redaction,
  channel classification, pattern scoring) using the same config files a
  Gemini prompt would be given, so the pipeline is genuinely testable end
  to end today.
- VertexGeminiClient: the production client (AKIYESI_LLM_BACKEND=
  vertex_gemini). It loads prompts/*.md (versioned, never inlined, per
  CLAUDE.md) as each call's system_instruction, calls Vertex AI's
  generate_content with response_mime_type="application/json", and hands
  the raw JSON to a pure parse_*_response function below. That split is
  deliberate: this sandbox (and the developer's own device sandbox -- see
  docs/ai-usage.md) cannot reach generativelanguage.googleapis.com or
  aiplatform.googleapis.com at all, confirmed by direct request, so the
  network-calling half of this class has no automated test coverage here.
  The parse_*_response functions are pure and fully unit-tested (see
  tests/test_llm_gemini_parsing.py) against response shapes taken from
  each prompt file's own worked example. Before this backend is trusted
  for a live demo, run scripts/smoke_test_gemini.py on a machine with
  real GCP credentials and network access -- that script, not this
  module's test coverage, is what verifies the network-calling half.

Swap which one the app uses via AKIYESI_LLM_BACKEND=rule_based|vertex_gemini
(app/pipeline.py reads this once at startup). rule_based stays the default,
so nothing about the tested, demoed pipeline changes unless that variable
is set.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Protocol

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# The only four category keys any redact() implementation may emit --
# config/redaction_terms.yaml, app/redaction.py, app/profiling_guard.py and
# the test suite all key on exactly this set.
CANONICAL_REDACTION_CATEGORIES = (
    "nationality",
    "ethnicity_tribe",
    "religion",
    "stranger_or_foreigner_markers",
)

VALID_CHANNELS = ("normal", "protected")


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


def parse_redaction_response(data: Dict) -> RedactionResult:
    """Validate + convert a Gemini redaction-prompt JSON reply.

    Pure, no network -- this is what tests/test_llm_gemini_parsing.py
    exercises directly, with response shapes copied from
    prompts/redaction_v1.md's own worked example plus deliberately-broken
    variants (missing key, wrong type, unknown category). Raises ValueError
    on anything that doesn't satisfy the contract in prompts/redaction_v1.md
    rather than silently passing bad data downstream -- a model response is
    untrusted input, same as any other external API response.
    """
    if not isinstance(data, dict):
        raise ValueError(f"redaction response must be a JSON object, got {type(data).__name__}")
    if "redacted_text" not in data or "categories_redacted" not in data:
        raise ValueError(f"redaction response missing required key(s) 'redacted_text'/'categories_redacted': {data!r}")

    redacted_text = data["redacted_text"]
    categories = data["categories_redacted"]

    if not isinstance(redacted_text, str):
        raise ValueError(f"redaction response 'redacted_text' must be a string, got {type(redacted_text).__name__}")
    if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
        raise ValueError(f"redaction response 'categories_redacted' must be a list of strings, got {categories!r}")

    unknown = [c for c in categories if c not in CANONICAL_REDACTION_CATEGORIES]
    if unknown:
        raise ValueError(
            f"redaction response used unknown category key(s) {unknown!r}; "
            f"must be a subset of {CANONICAL_REDACTION_CATEGORIES!r}"
        )

    # De-dupe while preserving order, in case the model repeats a category.
    deduped: List[str] = []
    for c in categories:
        if c not in deduped:
            deduped.append(c)

    return RedactionResult(redacted_text=redacted_text, categories_redacted=deduped)


def parse_classification_response(data: Dict) -> str:
    """Validate + convert a Gemini classification-prompt JSON reply.

    Pure, no network. Raises ValueError rather than letting an unexpected
    value (a third channel name, a boolean, null) reach app/classifier.py,
    which only ever expects exactly "normal" or "protected".
    """
    if not isinstance(data, dict):
        raise ValueError(f"classification response must be a JSON object, got {type(data).__name__}")
    if "channel" not in data:
        raise ValueError(f"classification response missing required key 'channel': {data!r}")

    channel = data["channel"]
    if channel not in VALID_CHANNELS:
        raise ValueError(f"classification response 'channel' must be one of {VALID_CHANNELS}, got {channel!r}")

    return channel


def parse_extraction_response(data: Dict, expected_pattern_ids: List[str]) -> Dict[str, int]:
    """Validate + convert a Gemini extraction-prompt JSON reply.

    Pure, no network. Returns exactly one non-negative int score per
    pattern_id in expected_pattern_ids (defaulting an omitted pattern to 0,
    since "no evidence" and "not mentioned" are the same signal here) and
    deliberately drops any 'time_of_day' key the model returns --
    app/extraction.py computes time_of_day independently via local regex
    (_TIME_HINTS), specifically so a model hallucinating a bad value there
    can never reach the pipeline.
    """
    if not isinstance(data, dict):
        raise ValueError(f"extraction response must be a JSON object, got {type(data).__name__}")
    if "scores" not in data:
        raise ValueError(f"extraction response missing required key 'scores': {data!r}")

    scores = data["scores"]
    if not isinstance(scores, dict):
        raise ValueError(f"extraction response 'scores' must be a JSON object, got {type(scores).__name__}")

    result: Dict[str, int] = {}
    for pattern_id in expected_pattern_ids:
        raw = scores.get(pattern_id, 0)
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise ValueError(f"extraction response score for {pattern_id!r} must be an int, got {raw!r}")
        if raw < 0:
            raise ValueError(f"extraction response score for {pattern_id!r} must be >= 0, got {raw}")
        result[pattern_id] = raw

    return result


class VertexGeminiClient:
    """Production client: real Vertex AI calls, wired to prompts/*.md.

    Construction fails fast and explains why, instead of silently behaving
    like RuleBasedClient, so a misconfigured deployment is loud rather than
    quietly wrong. Each public method below does the minimum: build the
    user-turn content, call self._generate_json (the one part of this class
    with no automated test coverage in this iteration -- see the module
    docstring), then hand the raw JSON to the matching pure parse_*_response
    function above, which is fully unit-tested.
    """

    def __init__(
        self,
        project_id: str,
        location: str = "us-central1",
        model_name: str = "gemini-2.0-flash-001",
    ):
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel
        except ImportError as exc:
            raise RuntimeError(
                "VertexGeminiClient requires google-cloud-aiplatform, which is not "
                "installed. Run `pip install -r requirements.txt` on a machine with "
                "network access, then set AKIYESI_LLM_BACKEND=vertex_gemini."
            ) from exc

        if not project_id:
            raise RuntimeError(
                "VertexGeminiClient requires AKIYESI_GCP_PROJECT to be set to a real "
                "GCP project ID with the Vertex AI API enabled (see README.md's "
                "Gemini setup section)."
            )

        self.project_id = project_id
        self.location = location
        self.model_name = model_name

        vertexai.init(project=project_id, location=location)

        self._redaction_prompt = (PROMPTS_DIR / "redaction_v1.md").read_text(encoding="utf-8")
        self._classification_prompt = (PROMPTS_DIR / "classification_v1.md").read_text(encoding="utf-8")
        self._extraction_prompt = (PROMPTS_DIR / "extraction_v1.md").read_text(encoding="utf-8")

        self._redaction_model = GenerativeModel(model_name, system_instruction=self._redaction_prompt)
        self._classification_model = GenerativeModel(model_name, system_instruction=self._classification_prompt)
        self._extraction_model = GenerativeModel(model_name, system_instruction=self._extraction_prompt)

    def _generate_json(self, model, user_content: str) -> Dict:
        """Call Gemini with JSON output forced, and parse the raw text.

        NOT exercised by the automated test suite in this iteration: the
        sandbox this was built in, and the developer's own device sandbox,
        both return 403 from every model-provider host tried (see
        docs/ai-usage.md for the exact hosts and responses), so there is no
        network path here to actually make this call. Every error case
        below is still handled explicitly -- a safety-filtered response, a
        malformed reply, an SDK/network exception -- so a real failure in
        the field is loud and specific rather than an unhandled exception
        deep in the pipeline. scripts/smoke_test_gemini.py is what proves
        this method actually works, on a machine that can reach Vertex AI.
        """
        from vertexai.generative_models import GenerationConfig

        try:
            response = model.generate_content(
                user_content,
                generation_config=GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0,
                ),
            )
        except Exception as exc:  # noqa: BLE001 -- surface any SDK/network failure clearly
            raise RuntimeError(f"Vertex AI call failed: {exc}") from exc

        raw_text = getattr(response, "text", None)
        if not raw_text:
            raise RuntimeError(
                f"Vertex AI returned no text (commonly a safety filter blocking the "
                f"response): {response!r}"
            )

        # Defensive: response_mime_type="application/json" should return
        # bare JSON, but strip a ```json fence if the model adds one anyway.
        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`")
            if raw_text.lower().startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Vertex AI response was not valid JSON: {raw_text!r}") from exc

    def redact(self, text: str, terms: Dict[str, List[str]]) -> RedactionResult:
        # `terms` is intentionally unused here: the categories to remove
        # are fully specified in prompts/redaction_v1.md's system
        # instruction, with worked examples -- that generalisation past an
        # exact phrase list is the entire reason to use a model instead of
        # RuleBasedClient, which is the implementation that actually needs
        # `terms` (config/redaction_terms.yaml).
        data = self._generate_json(self._redaction_model, text)
        return parse_redaction_response(data)

    def classify_channel(self, text: str, protected_indicator_terms: List[str]) -> str:
        # Same reasoning as redact(): the classification criteria and
        # worked examples live in prompts/classification_v1.md, not in
        # protected_indicator_terms (app/classifier.py's own fallback list).
        data = self._generate_json(self._classification_model, text)
        return parse_classification_response(data)

    def score_patterns(self, text: str, pattern_keywords: Dict[str, List[str]]) -> Dict[str, int]:
        # Unlike the two methods above, prompts/extraction_v1.md requires
        # patterns to be "supplied at call time" (CLAUDE.md scalability
        # seam #3: pattern definition is config, not code), so
        # pattern_keywords has to be serialised into this call's user turn.
        patterns_block = "\n".join(
            f"- {pattern_id}: {', '.join(keywords) if keywords else '(no keyword hints for this locale)'}"
            for pattern_id, keywords in pattern_keywords.items()
        )
        user_content = f"Patterns:\n{patterns_block}\n\nObservation: {text}"
        data = self._generate_json(self._extraction_model, user_content)
        return parse_extraction_response(data, expected_pattern_ids=list(pattern_keywords.keys()))


def get_llm_client() -> LLMClient:
    import os

    backend = os.environ.get("AKIYESI_LLM_BACKEND", "rule_based")
    if backend == "rule_based":
        return RuleBasedClient()
    if backend == "vertex_gemini":
        project_id = os.environ["AKIYESI_GCP_PROJECT"]
        location = os.environ.get("AKIYESI_GCP_LOCATION", "us-central1")
        model_name = os.environ.get("AKIYESI_GEMINI_MODEL", "gemini-2.0-flash-001")
        return VertexGeminiClient(project_id=project_id, location=location, model_name=model_name)
    raise ValueError(f"unknown AKIYESI_LLM_BACKEND: {backend!r}")
