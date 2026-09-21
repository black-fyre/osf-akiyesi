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

Swap which one the app uses via AKIYESI_LLM_BACKEND=rule_based|anthropic_claude.
Claude is the default (get_llm_client below), wrapped in GuardedClaudeClient
so the rule-based lists stay a floor under it and a fallback behind it. The
test suite pins rule_based (tests/__init__.py) to stay offline.

(Parts of the history above are out of date: the SDK now installs, and
scripts/replay_demo_on_claude.py runs every demo scene on the real API.)
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Protocol

from app.textnorm import fold, replace_phrase

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

    def score_patterns(
        self, text: str, pattern_keywords: Dict[str, List[str]], pattern_names: Optional[Dict[str, str]] = None
    ) -> Dict[str, int]:
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
            placeholder = "[person]" if category == "stranger_or_foreigner_markers" else "[REDACTED]"
            # Longest phrases first so "Fulani herdsman" matches before "Fulani".
            for phrase in sorted(phrases, key=len, reverse=True):
                # Whole-phrase (word-boundary) match, not substring search --
                # without it, a short entry like "Tiv" false-positive-matches
                # inside "operatives" or "relatives". Caught during seed
                # replay (see docs/ai-usage.md) before this shipped.
                # Tone marks are ignored (app/textnorm.py), so a Yoruba
                # word matches whether or not the sender typed its marks.
                redacted, hit = replace_phrase(redacted, phrase, placeholder)
                category_matched = category_matched or hit
            if category_matched:
                categories_hit.append(category)
        # Collapse doubled placeholders / whitespace left behind by
        # substitution so the redacted text reads cleanly.
        redacted = re.sub(r"\s+", " ", redacted).strip()
        redacted = re.sub(r"(\[person\]\s*){2,}", "[person] ", redacted)
        redacted = re.sub(r"(\[REDACTED\]\s*){2,}", "[REDACTED] ", redacted)
        return RedactionResult(redacted_text=redacted, categories_redacted=categories_hit)

    def classify_channel(self, text: str, protected_indicator_terms: List[str]) -> str:
        folded = fold(text)
        for term in protected_indicator_terms:
            if fold(term) in folded:
                return "protected"
        return "normal"

    def score_patterns(
        self, text: str, pattern_keywords: Dict[str, List[str]], pattern_names: Optional[Dict[str, str]] = None
    ) -> Dict[str, int]:
        folded = fold(text)
        scores: Dict[str, int] = {}
        for pattern_id, keywords in pattern_keywords.items():
            score = 0
            for kw in keywords:
                if fold(kw) in folded:
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


def _first_json_object(raw_text: str) -> Dict:
    """The first JSON object in a model reply, ignoring anything around it.

    The prompts ask for bare JSON, but a reply may come wrapped in a ```json
    fence and followed by an explanation. The earlier version stripped only
    backticks at the very ends, so any trailing prose broke json.loads, and
    every extraction call on Sonnet 4.5 silently fell back to the keyword
    lists (tests/test_llm_anthropic_client_wiring.py now pins this).
    """
    start = raw_text.find("{")
    if start == -1:
        raise RuntimeError(f"Anthropic API response was not valid JSON: {raw_text!r}")
    try:
        data, _end = json.JSONDecoder().raw_decode(raw_text, start)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Anthropic API response was not valid JSON: {raw_text!r}") from exc
    return data


_ANSWER_CACHE_SIZE = 1024


def _load_system_prompt(filename: str) -> str:
    """The model-facing part of a prompts/ file: everything from
    "## System instruction" down. The header above it (which code uses the
    prompt, what changed since the last version) is for people, and would
    only be noise, and tokens, in every request."""
    text = (PROMPTS_DIR / filename).read_text(encoding="utf-8")
    # A heading on its own line: the header quotes the phrase, and a plain
    # find() matched that quote and sent the whole file (a test caught it).
    heading = re.search(r"^## System instruction[^\n]*$", text, re.MULTILINE)
    return text[heading.end():].strip() if heading else text


def _observation(text: str) -> str:
    # The prompts treat everything inside these tags as untrusted data. A
    # sender cannot close the tag early and write instructions after it.
    return f"<observation>\n{text.replace('</observation', '</ observation')}\n</observation>"


_WORD = re.compile(r"\w+", re.UNICODE)
_PLACEHOLDER_WORDS = {"redacted", "person"}


def words_added_by_redaction(original: str, redacted: str) -> List[str]:
    """Words in a redaction that the sender never wrote (placeholders aside).

    Redaction may only remove. A model that rewrites, summarises, translates
    or follows an instruction hidden in the message produces words that were
    not there, and the report would then describe something nobody saw.
    GuardedClaudeClient discards such a redaction. Tone marks and case are
    ignored, so a model restoring or dropping a mark is not a change.
    """
    source = set(_WORD.findall(fold(original)))
    return [w for w in _WORD.findall(fold(redacted)) if w not in source and w not in _PLACEHOLDER_WORDS]


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

    def __init__(self, api_key: str, model_name: str = "claude-haiku-4-5-20251001"):
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
        # A live demo cannot wait on the SDK's default ten-minute timeout.
        # A call that fails fast lets GuardedClaudeClient fall back to the
        # rule-based lists, so the message still lands. Worst case with one
        # retry is about 20s; a normal call is under a second.
        self._client = anthropic.Anthropic(api_key=api_key, timeout=10.0, max_retries=1)

        self._redaction_prompt = _load_system_prompt("redaction_v2.md")
        self._classification_prompt = _load_system_prompt("classification_v2.md")
        self._extraction_prompt = _load_system_prompt("extraction_v2.md")

        # Answers already given, keyed by a hash of (call, request). The
        # demo replays the same scenes and ingest retries the same payloads,
        # so a repeat costs nothing and returns at once. Keys are digests
        # and values are parsed replies (redacted text at most), so the raw
        # message is never held here.
        self._answers: "OrderedDict[str, Dict]" = OrderedDict()
        self._answers_lock = threading.Lock()

    def _generate_json(self, system_prompt: str, user_content: str) -> Dict:
        """Call Claude and return the first JSON object in its reply.

        Not structured outputs (output_config.format), on purpose: measured
        on Haiku 4.5 on 21 Sep 2026, the schema added ~230 input tokens and
        ~0.4s to every call, and a message makes two calls back to back
        (docs/ai-usage.md). The stop sequence below plus _first_json_object
        already cope with a fenced reply and a trailing explanation, and
        the parse_*_response functions reject any category or channel
        outside the allowed set. Any failure falls back to the word lists.
        """
        key = hashlib.sha256(
            json.dumps([self.model_name, system_prompt, user_content]).encode("utf-8")
        ).hexdigest()
        with self._answers_lock:
            if key in self._answers:
                self._answers.move_to_end(key)
                return self._answers[key]

        try:
            response = self._client.messages.create(
                model=self.model_name,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
                # Claude tends to answer "```json {...} ```" and then write a
                # "Reasoning:" paragraph. Stopping at the closing fence saves
                # the seconds spent generating an explanation nobody reads.
                stop_sequences=["\n```"],
            )
        except Exception as exc:  # noqa: BLE001 -- surface any SDK/network failure clearly
            raise RuntimeError(f"Anthropic API call failed: {exc}") from exc

        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason in ("refusal", "max_tokens"):
            # A refusal carries no JSON; a max_tokens stop carries cut-off
            # JSON. Either way the rule-based lists take this step.
            raise RuntimeError(f"Anthropic API stopped with stop_reason={stop_reason!r}")

        texts = [
            block.text
            for block in (getattr(response, "content", None) or [])
            if getattr(block, "type", "text") == "text" and getattr(block, "text", None)
        ]
        if not texts:
            raise RuntimeError(f"Anthropic API returned no text content: {response!r}")
        data = _first_json_object(texts[0])

        with self._answers_lock:
            self._answers[key] = data
            while len(self._answers) > _ANSWER_CACHE_SIZE:
                self._answers.popitem(last=False)
        return data

    def warm_up(self) -> Optional[str]:
        """Open the connection and check the model before the first message.

        Two tiny calls, in the background at server start: the TLS
        handshake and the first compile of each reply schema happen here
        rather than on a resident's first message, and a model id the key
        cannot use is reported at startup instead of turning every message
        into a silent fallback. Returns None, or what went wrong.
        """
        try:
            self.classify_channel("warm-up: a parked car on the street", [])
            self.redact("warm-up: a parked car on the street", {})
        except Exception as exc:  # noqa: BLE001
            return str(exc)
        return None

    def redact(self, text: str, terms: Dict[str, List[str]]) -> RedactionResult:
        # `terms` is intentionally unused here: the categories to remove
        # are fully specified in prompts/redaction_v2.md's system prompt,
        # with worked examples -- that generalisation past an exact phrase
        # list is the entire reason to use a model instead of
        # RuleBasedClient, which is the implementation that actually needs
        # `terms` (config/redaction_terms.yaml). GuardedClaudeClient runs
        # those lists over this result as a floor.
        data = self._generate_json(self._redaction_prompt, _observation(text))
        return parse_redaction_response(data)

    def classify_channel(self, text: str, protected_indicator_terms: List[str]) -> str:
        # Same reasoning as redact(): the classification criteria and
        # worked examples live in prompts/classification_v2.md, not in
        # protected_indicator_terms (app/classifier.py's own fallback list).
        data = self._generate_json(self._classification_prompt, _observation(text))
        return parse_classification_response(data)

    def score_patterns(
        self, text: str, pattern_keywords: Dict[str, List[str]], pattern_names: Optional[Dict[str, str]] = None
    ) -> Dict[str, int]:
        # prompts/extraction_v2.md requires patterns to be "supplied at
        # call time" (CLAUDE.md scalability seam #3: pattern definition is
        # config, not code), so the patterns are serialised into this
        # call's user turn.
        names = pattern_names or {}
        patterns_block = "\n".join(
            f"- {pattern_id}"
            + (f" ({names[pattern_id]})" if names.get(pattern_id) else "")
            + f": {', '.join(keywords) if keywords else '(no cue phrases for this language)'}"
            for pattern_id, keywords in pattern_keywords.items()
        )
        user_content = f"<patterns>\n{patterns_block}\n</patterns>\n\n{_observation(text)}"
        ids = list(pattern_keywords.keys())
        data = self._generate_json(self._extraction_prompt, user_content)
        return parse_extraction_response(data, expected_pattern_ids=ids)


_CATEGORY_WORDS = {
    "nationality": "nationality",
    "ethnicity_tribe": "ethnic group",
    "religion": "religion",
    "stranger_or_foreigner_markers": "stranger wording",
}


class GuardedClaudeClient:
    """Claude, with the rule-based lists as a floor under it and a fallback
    behind it. This is what AKIYESI_LLM_BACKEND=anthropic_claude runs.

    Floor: Claude's redaction follows prompts/redaction_v1.md, which
    generalises past any word list, but the config lists
    (config/redaction_terms.yaml, including Yoruba) still run over Claude's
    output, so anything on a list is removed even if the model left it in.
    Likewise a message either reader thinks is about the guards goes to the
    protected channel. The model can widen protection, never narrow it.

    Fallback: if a call fails (network, timeout, a reply that breaks the
    JSON contract), that one step uses the rule-based client instead, so a
    message is never lost to an API error in the middle of a demo.

    Both are recorded as plain-language events (no message content) that
    the demo console shows, so the audience sees which reader did what.
    """

    backend_name = "claude"

    def __init__(self, claude: "AnthropicClient", rules: RuleBasedClient):
        self.claude = claude
        self.rules = rules
        self.model_name = getattr(claude, "model_name", "")
        self._events: List[str] = []
        # The channel and pattern calls run on two threads (app/pipeline.py),
        # and the HTTP server runs requests on threads of its own.
        self._events_lock = threading.Lock()

    def _note(self, event: str) -> None:
        with self._events_lock:
            self._events.append(event)

    def drain_events(self) -> List[str]:
        with self._events_lock:
            events, self._events = self._events, []
        return events

    def warm_up(self) -> Optional[str]:
        warm = getattr(self.claude, "warm_up", None)
        return warm() if warm else None

    def redact(self, text: str, terms: Dict[str, List[str]]) -> RedactionResult:
        try:
            first = self.claude.redact(text, terms)
        except Exception:  # noqa: BLE001 -- any failure: fall back, never lose the message
            self._note("Claude did not answer for redaction, so the word lists in config did it.")
            return self.rules.redact(text, terms)
        if words_added_by_redaction(text, first.redacted_text):
            self._note(
                "Claude's redaction changed the wording instead of only removing identity words, "
                "so the word lists in config did it."
            )
            return self.rules.redact(text, terms)
        floor = self.rules.redact(first.redacted_text, terms)
        categories = list(first.categories_redacted)
        extra = [c for c in floor.categories_redacted if c not in categories]
        if extra:
            self._note(
                "The word lists in config also removed something Claude left in ("
                + ", ".join(_CATEGORY_WORDS.get(c, c) for c in extra) + ")."
            )
        return RedactionResult(redacted_text=floor.redacted_text, categories_redacted=categories + extra)

    def classify_channel(self, text: str, protected_indicator_terms: List[str]) -> str:
        by_rules = self.rules.classify_channel(text, protected_indicator_terms)
        try:
            by_claude = self.claude.classify_channel(text, protected_indicator_terms)
        except Exception:  # noqa: BLE001
            self._note("Claude did not answer for the channel check, so the word lists in config did it.")
            return by_rules
        if by_rules == "protected" and by_claude == "normal":
            self._note("Claude read this as a normal report; the word lists in config sent it to the protected channel.")
        return "protected" if "protected" in (by_claude, by_rules) else "normal"

    def score_patterns(
        self, text: str, pattern_keywords: Dict[str, List[str]], pattern_names: Optional[Dict[str, str]] = None
    ) -> Dict[str, int]:
        try:
            if pattern_names:
                scores = self.claude.score_patterns(text, pattern_keywords, pattern_names=pattern_names)
            else:
                scores = self.claude.score_patterns(text, pattern_keywords)
        except Exception:  # noqa: BLE001
            self._note("Claude did not answer for pattern matching, so the keyword lists in config did it.")
            return self.rules.score_patterns(text, pattern_keywords)
        # Claude decides here (it is better than a word list at telling a
        # lost goat from casing), but say so when it overrules the lists,
        # so a presenter can see the difference.
        if not any(scores.values()):
            by_rules = self.rules.score_patterns(text, pattern_keywords)
            matched = [pid for pid, s in by_rules.items() if s > 0]
            if matched:
                self._note(
                    "Claude matched this to no pattern; the keyword lists would have filed it under "
                    + ", ".join(matched) + "."
                )
        return scores


def get_llm_client() -> LLMClient:
    """Claude by default (AKIYESI_LLM_BACKEND=anthropic_claude, or unset).

    If Claude was asked for explicitly and cannot be set up (no `anthropic`
    package, no key), this raises: a misconfigured deployment should be
    loud. If the backend was left unset, it warns on stderr and runs the
    rule-based client, so a fresh clone still starts. The test suite pins
    rule_based (tests/__init__.py) so it stays repeatable and offline.
    """
    import os
    import sys

    explicit = os.environ.get("AKIYESI_LLM_BACKEND")
    backend = explicit or "anthropic_claude"
    if backend == "rule_based":
        return RuleBasedClient()
    if backend == "anthropic_claude":
        api_key = os.environ.get("AKIYESI_ANTHROPIC_API_KEY", "")
        model_name = os.environ.get("AKIYESI_CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        try:
            claude = AnthropicClient(api_key=api_key, model_name=model_name)
        except RuntimeError as exc:
            if explicit:
                raise
            print(f"Akiyesi: Claude is not set up ({exc}) Running the rule-based client instead.", file=sys.stderr)
            return RuleBasedClient()
        return GuardedClaudeClient(claude, RuleBasedClient())
    raise ValueError(f"unknown AKIYESI_LLM_BACKEND: {backend!r}")
