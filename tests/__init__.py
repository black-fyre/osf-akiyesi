

# The app defaults to Claude (app/llm.py get_llm_client). The suite pins the
# deterministic rule-based client so it is repeatable, offline and free, even
# when run from a shell that has AKIYESI_LLM_BACKEND=anthropic_claude
# exported. Tests that exercise the Claude client construct it themselves.
import os as _os

_os.environ["AKIYESI_LLM_BACKEND"] = "rule_based"
