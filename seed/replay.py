#!/usr/bin/env python3
"""Seed replay harness.

Feeds seed/reports.json through the real ingest pipeline against a fresh
in-memory store and prints a per-community, per-pattern summary: distinct
senders, span, resulting status, and (CLAUDE.md "Threshold sensitivity",
day 4 plan item) how that status would change at looser or stricter
corroboration thresholds. This is the apparatus the deck's threshold-
sensitivity slide is built from -- it reframes "are your numbers right"
into "here is the tuning method, per community".

Usage:
    python3 seed/replay.py                       # seed/reports.json, suggested thresholds
    python3 seed/replay.py --file seed/bodija_scale_replay.json --profile suggested
    python3 seed/replay.py --sensitivity         # loose / suggested / strict side by side
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import clustering, ingest
from app.config import Community, NormalChannelThresholds, SpanThreshold, get_config
from app.llm import RuleBasedClient
from app.storage import make_store

SEED_DIR = Path(__file__).resolve().parent

PROFILES = {
    "loose": NormalChannelThresholds(
        watch=SpanThreshold(min_distinct_senders=2, min_span_days=1),
        escalate=SpanThreshold(min_distinct_senders=3, min_span_days=2),
    ),
    "suggested": None,  # use each community's configured thresholds as-is
    "strict": NormalChannelThresholds(
        watch=SpanThreshold(min_distinct_senders=4, min_span_days=4),
        escalate=SpanThreshold(min_distinct_senders=7, min_span_days=5),
    ),
}


def _with_profile(community: Community, profile: str) -> Community:
    override = PROFILES[profile]
    if override is None:
        return community
    new_thresholds = replace(community.thresholds, normal_channel=override)
    return replace(community, thresholds=new_thresholds)


def replay(seed_path: Path, profile: str = "suggested") -> None:
    config = get_config()
    llm = RuleBasedClient()
    store = make_store(":memory:")

    raw = json.loads(seed_path.read_text(encoding="utf-8"))
    payloads = [r for r in raw if not r.get("_note")]

    for payload in payloads:
        ingest.receive_webhook(payload, config, llm, store)

    print(f"\n=== replay: {seed_path.name}  (profile: {profile}) ===")
    print(f"{len(payloads)} inbound messages processed\n")

    by_community = {}
    for r in store.all_reports():
        by_community.setdefault(r.community_id, []).append(r)

    for community_id, reports in sorted(by_community.items()):
        community = config.community_by_id(community_id)
        if community is None:
            continue
        community = _with_profile(community, profile)

        stored_statuses = {}
        for r in reports:
            stored_statuses[r.status] = stored_statuses.get(r.status, 0) + 1

        normal_reports = [r for r in reports if r.channel == "normal"]
        clusters = clustering.compute_clusters(normal_reports, community, patterns=config.patterns)
        protected_reports = [r for r in reports if r.channel == "protected"]
        protected = clustering.protected_items(protected_reports, community)

        print(f"-- {community.name} ({community_id}) --")
        print(f"   report status counts: {stored_statuses}")
        for c in clusters:
            print(
                f"   [normal]    pattern={c.pattern_id:<20} senders={c.distinct_senders:<3} "
                f"span={c.span_days:5.1f}d  redacted={c.profiling.redacted_fraction:4.0%}  "
                f"status={c.status}"
            )
        for item in protected:
            print(
                f"   [protected] pattern={item.report.pattern_id:<20} senders=1   span=  0.0d  "
                f"redacted={item.profiling.redacted_fraction:4.0%}  status={item.status}"
            )
        print()


def sensitivity(seed_path: Path) -> None:
    for profile in ("loose", "suggested", "strict"):
        replay(seed_path, profile=profile)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default=str(SEED_DIR / "reports.json"))
    parser.add_argument("--profile", default="suggested", choices=list(PROFILES))
    parser.add_argument("--sensitivity", action="store_true", help="run all three profiles")
    args = parser.parse_args()

    seed_path = Path(args.file)
    if args.sensitivity:
        sensitivity(seed_path)
    else:
        replay(seed_path, profile=args.profile)


if __name__ == "__main__":
    main()
