#!/usr/bin/env python3
"""Smoke test for app.llm.VertexGeminiClient against the REAL Vertex AI API.

Why this script exists: neither sandbox this project was built in (the
cloud environment, or the developer's own device sandbox) has network
access to generativelanguage.googleapis.com or aiplatform.googleapis.com --
both returned 403 from a direct request in both places (see
docs/ai-usage.md for the exact hosts/status codes). That means
VertexGeminiClient's three public methods (redact, classify_channel,
score_patterns) are wired up and unit-tested against a fake SDK
(tests/test_llm_gemini_client_wiring.py) and the response-parsing logic is
fully tested (tests/test_llm_gemini_parsing.py), but the actual network
call has never been executed. This script is what closes that gap: run it
yourself, on a machine with real GCP credentials and outbound network
access, before trusting AKIYESI_LLM_BACKEND=vertex_gemini for a live demo.

Setup (see README.md's "Real Gemini / Vertex AI setup" section for the
full walkthrough):
    1. A GCP project with the Vertex AI API enabled.
    2. Application Default Credentials available, e.g.:
         gcloud auth application-default login
    3. pip install -r requirements.txt   (installs google-cloud-aiplatform)
    4. export AKIYESI_GCP_PROJECT=<your-project-id>
       export AKIYESI_GCP_LOCATION=us-central1        # or your region
       export AKIYESI_GEMINI_MODEL=gemini-2.0-flash-001  # optional, this is the default

Run:
    python3 scripts/smoke_test_gemini.py

What it does: three real Vertex AI calls (one per prompt: redaction,
classification, extraction), each with the same input as that prompt
file's own worked example, printing what came back so you can eyeball it
against the worked example's expected output. It does NOT touch
AKIYESI_LLM_BACKEND or any other app state -- it imports VertexGeminiClient
directly and calls it, the same way app/pipeline.py would if that env var
were set to vertex_gemini.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm import VertexGeminiClient  # noqa: E402


def _fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    project_id = os.environ.get("AKIYESI_GCP_PROJECT")
    if not project_id:
        _fail("AKIYESI_GCP_PROJECT is not set. Export it to your GCP project ID and re-run.")

    location = os.environ.get("AKIYESI_GCP_LOCATION", "us-central1")
    model_name = os.environ.get("AKIYESI_GEMINI_MODEL", "gemini-2.0-flash-001")

    print(f"Connecting to Vertex AI: project={project_id!r} location={location!r} model={model_name!r}")
    try:
        client = VertexGeminiClient(project_id=project_id, location=location, model_name=model_name)
    except RuntimeError as exc:
        _fail(f"could not construct VertexGeminiClient: {exc}")
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
