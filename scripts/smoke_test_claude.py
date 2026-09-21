#!/usr/bin/env python3
"""Smoke test for app.llm.AnthropicClient against the REAL Anthropic API.

Why this script exists: the `anthropic` Python package cannot be
pip-installed in the sandbox this project was built in -- there is no
route to pypi.org (confirmed by direct request; see docs/ai-usage.md).
That means AnthropicClient's three public methods (redact,
classify_channel, score_patterns) are wired up and unit-tested against a
fake SDK (tests/test_llm_anthropic_client_wiring.py) and the
response-parsing logic is fully tested (tests/test_llm_response_parsing.py),
but the actual network call has never been executed from this sandbox.
Note this is a narrower gap than it sounds: api.anthropic.com itself IS
reachable from here (a direct, unauthenticated request to it returns 401,
i.e. a real, responsive endpoint) -- what's missing is only the SDK
package and a real API key, not network access to the host. This script
is what closes that last gap: run it yourself, on a machine where you can
`pip install anthropic`, before trusting AKIYESI_LLM_BACKEND=
anthropic_claude for a live demo.

Setup (see README.md's "Real Claude API setup" section for the full
walkthrough):
    1. An Anthropic API key from https://console.anthropic.com/
    2. pip install -r requirements.txt   (installs the anthropic package)
    3. export AKIYESI_ANTHROPIC_API_KEY=<your-api-key>
       export AKIYESI_CLAUDE_MODEL=claude-haiku-4-5-20251001  # optional, this is the default

Run:
    python3 scripts/smoke_test_claude.py

What it does: three real Anthropic API calls (one per prompt: redaction,
classification, extraction), each with the same input as that prompt
file's own worked example, printing what came back so you can eyeball it
against the worked example's expected output. It does NOT touch
AKIYESI_LLM_BACKEND or any other app state -- it imports AnthropicClient
directly and calls it, the same way app/pipeline.py would if that env var
were set to anthropic_claude.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm import AnthropicClient  # noqa: E402
from app.envfile import load_env_file  # noqa: E402

load_env_file()  # picks up AKIYESI_ANTHROPIC_API_KEY from .env, no export needed


def _fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    api_key = os.environ.get("AKIYESI_ANTHROPIC_API_KEY", "")
    if not api_key:
        _fail("AKIYESI_ANTHROPIC_API_KEY is not set. Export it to your Anthropic API key and re-run.")

    model_name = os.environ.get("AKIYESI_CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    print(f"Connecting to the Anthropic API: model={model_name!r}")
    try:
        client = AnthropicClient(api_key=api_key, model_name=model_name)
    except RuntimeError as exc:
        _fail(f"could not construct AnthropicClient: {exc}")
        return

    print("\n--- 1/3: redact() -- prompts/redaction_v1.md worked example ---")
    redaction_input = (
        "A Fulani stranger was seen unloading sacks into the empty house on our street around 2am."
    )
    print(f"input:  {redaction_input!r}")
    try:
        result = client.redact(redaction_input, terms={})
    except Exception as exc:  # noqa: BLE001 -- smoke test, show any failure directly
        _fail(f"redact() raised: {exc}")
        return
    print(f"output: redacted_text={result.redacted_text!r}")
    print(f"        categories_redacted={result.categories_redacted!r}")
    print("expected (from prompts/redaction_v1.md): ethnicity_tribe + stranger_or_foreigner_markers,")
    print("  with 'unloading sacks', 'empty house', 'our street', 'around 2am' all surviving untouched.")

    print("\n--- 2/3: classify_channel() -- prompts/classification_v1.md worked examples ---")
    for classification_input, expected in [
        ("The gateman is asking for a bribe before he lets visitors in at night.", "protected"),
        ("Two men were photographing the houses from a parked car.", "normal"),
    ]:
        print(f"input:    {classification_input!r}")
        try:
            channel = client.classify_channel(classification_input, protected_indicator_terms=[])
        except Exception as exc:  # noqa: BLE001
            _fail(f"classify_channel() raised: {exc}")
            return
        print(f"output:   {channel!r}  (expected: {expected!r})")

    print("\n--- 3/3: score_patterns() -- prompts/extraction_v1.md worked example ---")
    extraction_input = "Someone was checking gates along Alade Street block by block late last night."
    pattern_keywords = {
        "burglary_casing": ["checking gates", "loitering", "unfamiliar vehicle"],
        "explosives_storage": ["chemical drums", "storing explosives"],
    }
    print(f"input:    {extraction_input!r}")
    try:
        scores = client.score_patterns(extraction_input, pattern_keywords)
    except Exception as exc:  # noqa: BLE001
        _fail(f"score_patterns() raised: {exc}")
        return
    print(f"output:   {scores!r}")
    print("expected (from prompts/extraction_v1.md): burglary_casing=1, explosives_storage=0")

    print("\nAll three calls completed without raising. Eyeball the outputs above against the")
    print("'expected' lines -- this script checks that a JSON response came back and parsed")
    print("correctly, not that the model's judgement matches the worked example exactly.")


if __name__ == "__main__":
    main()
