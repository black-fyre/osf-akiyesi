#!/usr/bin/env python3
"""Replay every demo scene through the Claude reader and compare each
outcome with the one the scene declares.

The declared outcomes (app/demo.py SCENES and REMOTE_EXTRAS, `expect`) are
checked on every test run, but on the rule-based reader, because the suite
must be repeatable and offline. Claude's reading varies, so run this before
a live demo or a recording to see how the scenes land on Claude today.

    source .venv/bin/activate
    python3 scripts/replay_demo_on_claude.py

It reads AKIYESI_ANTHROPIC_API_KEY from .env. Each message makes three
Claude calls; a full replay is roughly 75 calls. Nothing is written to the
app's database (every scene runs on a fresh in-memory store).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.envfile import load_env_file  # noqa: E402

load_env_file()
os.environ.setdefault("AKIYESI_LLM_BACKEND", "anthropic_claude")

from app import demo  # noqa: E402
from app.config import get_config  # noqa: E402
from app.llm import get_llm_client  # noqa: E402
from app.server import AppContext  # noqa: E402
from app.storage import make_store  # noqa: E402


def outcome(scene, state, results):
    exp = scene["expect"]
    problems = []
    if "pattern_id" in exp:
        c = next((c for c in state["clusters"] if c["pattern_id"] == exp["pattern_id"]), None)
        if c is None:
            return [f"no {exp['pattern_id']} cluster (clusters: {[x['pattern_id'] for x in state['clusters']]})"]
        if "status" in exp and c["status"] != exp["status"]:
            problems.append(f"status {c['status']}, expected {exp['status']}")
        if "distinct_senders" in exp and c["distinct_senders"] != exp["distinct_senders"]:
            problems.append(f"{c['distinct_senders']} senders, expected {exp['distinct_senders']}")
        if exp.get("redacted") and c["redacted_count"] < 1:
            problems.append("nothing redacted")
    elif "status" in exp and state["counts"]["refused"] != 1:
        problems.append(f"refused {state['counts']['refused']}, expected 1")
    if "protected_waiting" in exp and state["protected_inbox"]["waiting"] != exp["protected_waiting"]:
        problems.append(f"{state['protected_inbox']['waiting']} protected, expected {exp['protected_waiting']}")
    if "noise" in exp and state["counts"]["noise"] != exp["noise"]:
        problems.append(f"{state['counts']['noise']} noise, expected {exp['noise']}")
    if "locale" in exp and any(r.get("locale") != exp["locale"] for r in results):
        problems.append("language not detected as expected")
    return problems


def main() -> int:
    config = get_config()
    reader = get_llm_client()
    if getattr(reader, "backend_name", "") != "claude":
        print("Claude is not set up (check AKIYESI_ANTHROPIC_API_KEY in .env and `pip install anthropic`).")
        return 2
    print(f"Replaying on Claude ({reader.model_name})\n")
    failures = 0
    for scene in demo.SCENES + demo.REMOTE_EXTRAS:
        ctx = AppContext(config=config, llm=reader, store=make_store(":memory:"), demo_mode=True)
        started = time.time()
        results = [demo.send_message(ctx, {**m, "community_id": scene["community_id"]}) for m in scene["messages"]]
        per_msg = (time.time() - started) / len(scene["messages"])
        state = demo.build_state(ctx, config.community_by_id(scene["community_id"]))
        problems = outcome(scene, state, results)
        failures += bool(problems)
        mark = "ok  " if not problems else "DIFF"
        print(f"{mark} {scene['title']:<38} {per_msg:4.1f}s per message")
        for p in problems:
            print(f"       {p}")
        for r in results:
            for event in (r.get("reader") or {}).get("events", []):
                print(f"       note: {event}")
    print(f"\n{failures} scene(s) landed differently on Claude than scripted.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
