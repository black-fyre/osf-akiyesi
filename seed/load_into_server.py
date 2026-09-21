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

    # For a recording: oke-ado-phase2 sits at Watch with 4 of 5 senders, and
    # the 5th is sent live from /demo/remote with N (see app/demo.py,
    # "staged recording"). The seeded Oke-Ado burglary reports alone already
    # reach Ready, so they are left out of this load (reports.json is not
    # changed) and the first four street-speaks messages are posted instead.
    python3 seed/load_into_server.py --hold-last oke-ado-phase2
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent
REPO_ROOT = SEED_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Communities that can be staged, and the seed id prefix of the cluster the
# staged scene replaces for that load.
HOLDABLE = {"oke-ado-phase2": "okeado-clean-"}


def staged_reports(seed_reports: list, community_id: str) -> list:
    """The seed minus the community's own burglary cluster, plus the first
    four street-speaks messages, dated from now."""
    from app import demo
    from app.config import get_config

    if community_id not in HOLDABLE:
        raise SystemExit(f"--hold-last supports {', '.join(HOLDABLE)}, not {community_id}")
    skip = HOLDABLE[community_id]
    kept = [r for r in seed_reports if not r["id"].startswith(skip)]
    return kept + demo.staged_payloads(get_config())


def load(seed_path: Path, base_url: str, hold_last: str = None) -> None:
    reports = [r for r in json.loads(seed_path.read_text(encoding="utf-8")) if not r.get("_note")]
    if hold_last:
        reports = staged_reports(reports, hold_last)
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
    parser.add_argument(
        "--hold-last",
        metavar="COMMUNITY_ID",
        help="stage that community at 4 of 5 senders, with the 5th left for the remote",
    )
    args = parser.parse_args()
    load(Path(args.file), args.url.rstrip("/"), args.hold_last)


if __name__ == "__main__":
    main()
