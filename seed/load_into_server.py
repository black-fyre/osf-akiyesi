#!/usr/bin/env python3
"""Posts a seed JSON file into a *running* app/server.py instance.

Unlike seed/replay.py (which runs reports through the pipeline in-process
and prints a summary, no server involved), this hits the real HTTP
webhook endpoint -- use it to pre-populate the desk UI before a live demo
or recording, so /desk and /protected-outbox already show a realistic
mix of clusters instead of starting empty.

Usage:
    python3 -m app.server &            # start the server first
    python3 seed/load_into_server.py   # then load the seed data
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent


def load(seed_path: Path, base_url: str) -> None:
    reports = [r for r in json.loads(seed_path.read_text(encoding="utf-8")) if not r.get("_note")]
    ok, fail = 0, 0
    for r in reports:
        req = urllib.request.Request(
            f"{base_url}/webhook/sms",
            data=json.dumps(r).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
                ok += 1
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print(f"failed: {r.get('id')}: {exc}")
    print(f"posted {ok} ok, {fail} failed, into {base_url}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default=str(SEED_DIR / "reports.json"))
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    load(Path(args.file), args.url.rstrip("/"))


if __name__ == "__main__":
    main()
