"""Pluggable model client used by redaction, classification and extraction.

CLAUDE.md specifies Claude via the Anthropic API, with every prompt in a
versioned prompts/ directory. This module defines the interface those
three pipeline stages code against (LLMClient) and two implementations:

- RuleBasedClient: deterministic, dependency-free, config-driven. This is
  the default backend (AKIYESI_LLM_BACKEND=rule_based) and what the demo
  and full test suite actually run, because the sandbox this was built in
  has no route to any model-provider *package registry* (see
  docs/ai-usage.md). It is not a placeholder that returns fake data; it
  does the real work (redaction, channel classification, pattern scoring)
  using the same config files a Claude prompt would be given, so the
  pipeline is genuinely testable end to end today.
- AnthropicClient: the production client (AKIYESI_LLM_BACKEND=
  anthropic_claude). It loads prompts/*.md (versioned, never inlined, per
  CLAUDE.md) as each call's system prompt, calls the Anthropic Messages
  API, and hands the raw JSON to a pure parse_*_response function below.
  That split is deliberate: the `anthropic` package cannot be pip-installed
  in this sandbox (no route to pypi.org -- see docs/ai-usage.md), so the
  network-calling half of this class has no automated test coverage here.
  Note this is a narrower gap than it first looks: api.anthropic.com
  itself IS reachable from this sandbox (confirmed by direct request --
  it returns 401 without a key, i.e. a real, responsive endpoint), unlike
  generativelanguage.googleapis.com / aiplatform.googleapis.com, which
  returned 403 (fully blocked) when an earlier iteration of this module
  targeted Gemini. What's missing here is only the SDK package and a real
  API key, not network access to the host itself. The parse_*_response
  functions are pure and fully unit-tested (see
  tests/test_llm_anthropic_parsing.py) against response shapes taken from
  each prompt file's own worked example, and
  tests/test_llm_anthropic_client_wiring.py proves this class calls a
  (faked) Anthropic SDK the way its documented contract requires. Before
  this backend is trusted for a live demo, run scripts/smoke_test_claude.py
  on a machine with `pip install anthropic` and a real API key -- that
  script, not this module's test coverage, is what verifies the network
  call itself.

Swap which one the app uses via AKIYESI_LLM_BACKEND=rule_based|anthropic_claude
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
    equivalent instruction a Claude prompt would be given.
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
    """Validate + convert a redaction-prompt JSON reply.

    Pure, no network -- this is what tests/test_llm_anthropic_parsing.py
    exercises directly, with response shapes copied from
    prompts/redaction_v1.md's own worked example plus deliberately-broken
    variants (missing key, wrong type, unknown category). Raises ValueError
    on anything that doesn't satisfy the contract in prompts/redaction_v1.md
    rather than silently passing bad data downstream -- a model response is
    untrusted input, same as any other external API response. Shared by
    every LLMClient implementation that talks to a real model: the JSON
    contract comes from the prompt file, not from any one provider's SDK.
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
    """Validate + convert a classification-prompt JSON reply.

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
    """Validate + convert an extraction-prompt JSON reply.

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


class AnthropicClient:
    """Production client: real Claude calls via the Anthropic Messages API.

    Construction fails fast and explains why, instead of silently behaving
    like RuleBasedClient, so a misconfigured deployment is loud rather than
    quietly wrong. Each public method below does the minimum: build the
    user-turn content, call self._generate_json (the one part of this class
    with no automated test coverage in this iteration -- see the module
    docstring), then hand the raw JSON to the matching pure parse_*_response
    function above, which is fully unit-tested.

    Unlike a per-prompt "model" object (the shape Vertex AI's SDK wants),
    the Anthropic SDK takes a system prompt per call rather than per client,
    so this class holds one `anthropic.Anthropic` client and three prompt
    strings, and passes the right prompt as `system=` on each call.
    """

    def __init__(self, api_key: str, model_name: str = "claude-sonnet-4-5-20250929"):
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "AnthropicClient requires the `anthropic` package, which is not "
                "installed. Run `pip install -r requirements.txt` on a machine with "
                "network access, then set AKIYESI_LLM_BACKEND=anthropic_claude."
            ) from exc

        if not api_key:
            raise RuntimeError(
                "AnthropicClient requires AKIYESI_ANTHROPIC_API_KEY to be set to a "
                "real Anthropic API key (see README.md's Real Claude API setup "
                "section)."
            )

        self.model_name = model_name
        self._client = anthropic.Anthropic(api_key=api_key)

        self._redaction_prompt = (PROMPTS_DIR / "redaction_v1.md").read_text(encoding="utf-8")
        self._classification_prompt = (PROMPTS_DIR / "classification_v1.md").read_text(encoding="utf-8")
        self._extraction_prompt = (PROMPTS_DIR / "extraction_v1.md").read_text(encoding="utf-8")

    def _generate_json(self, system_prompt: str, user_content: str) -> Dict:
        """Call Claude and parse the raw text as JSON.

        NOT exercised by the automated test suite in this iteration: the
        `anthropic` package cannot be installed in this sandbox (no route
        to pypi.org -- see docs/ai-usage.md), so there is no way to make
        this exact call here, even though the API host itself is reachable.
        Every error case below is still handled explicitly -- an empty
        response, a malformed reply, an SDK/network exception -- so a real
        failure in the field is loud and specific rather than an unhandled
        exception deep in the pipeline. scripts/smoke_test_claude.py is
        what proves this method actually works, on a machine that has the
        SDK installed and a real API key.
        """
        try:
            response = self._client.messages.create(
                model=self.model_name,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception as exc:  # noqa: BLE001 -- surface any SDK/network failure clearly
            raise RuntimeError(f"Anthropic API call failed: {exc}") from exc

        content = getattr(response, "content", None)
        raw_text = content[0].text if content else None
        if not raw_text:
            raise RuntimeError(f"Anthropic API returned no text content: {response!r}")

        # Defensive: the prompts ask for bare JSON, but strip a ```json
        # fence if the model adds one anyway.
        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`")
            if raw_text.lower().startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Anthropic API response was not valid JSON: {raw_text!r}") from exc

    def redact(self, text: str, terms: Dict[str, List[str]]) -> RedactionResult:
        # `terms` is intentionally unused here: the categories to remove
        # are fully specified in prompts/redaction_v1.md's system prompt,
        # with worked examples -- that generalisation past an exact phrase
        # list is the entire reason to use a model instead of
        # RuleBasedClient, which is the implementation that actually needs
        # `terms` (config/redaction_terms.yaml).
        data = self._generate_json(self._redaction_prompt, text)
        return parse_redaction_response(data)

    def classify_channel(self, text: str, protected_indicator_terms: List[str]) -> str:
        # Same reasoning as redact(): the classification criteria and
        # worked examples live in prompts/classification_v1.md, not in
        # protected_indicator_terms (app/classifier.py's own fallback list).
        data = self._generate_json(self._classification_prompt, text)
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
        data = self._generate_json(self._extraction_prompt, user_content)
        return parse_extraction_response(data, expected_pattern_ids=list(pattern_keywords.keys()))


def get_llm_client() -> LLMClient:
    import os

    backend = os.environ.get("AKIYESI_LLM_BACKEND", "rule_based")
    if backend == "rule_based":
        return RuleBasedClient()
    if backend == "anthropic_claude":
        api_key = os.environ.get("AKIYESI_ANTHROPIC_API_KEY", "")
        model_name = os.environ.get("AKIYESI_CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
        return AnthropicClient(api_key=api_key, model_name=model_name)
    raise ValueError(f"unknown AKIYESI_LLM_BACKEND: {backend!r}")
