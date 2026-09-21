"""Demo console support (served at /demo, see app/server.py).

The console is a front end for the same pipeline the SMS webhook feeds. It
exists so the system can be shown working in a few minutes, and it adds no
new rules: every message it sends goes through ingest.receive_webhook, the
same function the real webhook calls, and every threshold it draws comes
from clustering.resolve_thresholds, the same function the desk uses.

Three things are specific to a demo, and the console says so on screen:
  - Messages can be backdated (the payload's optional `date`). A real
    corroboration window is days long, and a demo is not.
  - The senders are fictional residents with fictional numbers.
  - Reset wipes every table, so a run can be replayed from a clean slate.
    That is why the console is only served when demo mode is on
    (AppContext.demo_mode, switched on by server.run() unless
    AKIYESI_DEMO_MODE=0), and every route here answers 404 when it is off.

The privacy line the product draws is kept in the console: protected-channel
message text and patterns are never returned by /demo/state or by /demo/send.
The console shows that a protected report arrived and where it went, and the
text itself is only reachable on the landlord association's own inbox page.

SCENES is the demo script as data. Each scene declares the outcome it is
meant to produce (`expect`), and tests/test_demo_console.py replays every
scene through the real pipeline and checks that outcome, so the script
cannot drift away from the rules it demonstrates.
"""
from __future__ import annotations

import os
import uuid
from datetime import timedelta
from typing import Any, Dict, List, Optional

from app import clustering, ingest
from app.models import utcnow

DEMO_ENV = "AKIYESI_DEMO_MODE"
MAX_TEXT_LENGTH = 600
MAX_DAYS_AGO = 30

# Fictional residents. The numbers are deliberately not valid Nigerian
# numbers (national numbers do not start with 0), so no real person can be
# hit by a demo run.
RESIDENTS: List[Dict[str, Any]] = [
    {"id": i, "label": f"Resident {i}", "phone": f"+23400000{i:04d}"} for i in range(1, 13)
]
_PHONE_BY_RESIDENT = {r["id"]: r["phone"] for r in RESIDENTS}

OKE_ADO = "oke-ado-phase2"
BODIJA = "bodija-close-9"


def demo_mode_from_env(default: bool = True) -> bool:
    raw = os.environ.get(DEMO_ENV)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "off", "no", "")


def _m(resident: int, days_ago: float, text: str, line: str = "normal") -> Dict[str, Any]:
    return {"resident": resident, "days_ago": days_ago, "line": line, "text": text}


SCENES: List[Dict[str, Any]] = [
    {
        "id": "street-speaks",
        "title": "The street speaks",
        "community_id": OKE_ADO,
        "beat": "Five neighbours on basic phones, over four days. No single text is enough. Together they are a pattern.",
        "watch_for": "The bars fill one sender at a time. Nothing reaches the committee until five different people have reported across three days.",
        "messages": [
            _m(1, 4, "Strange vehicle parked outside our gate for over an hour last night, nobody came out."),
            _m(2, 3, "Two men were unloading sacks at the empty house on Adeoye street around midnight."),
            _m(3, 2, "A man was checking gates and testing the gate on the next street, then left on a bike."),
            _m(4, 1, "Men unloading at night again at the same empty house, they switched off their headlights."),
            _m(5, 0, "Someone was photographing houses on my street this evening and counting houses."),
        ],
        "expect": {"pattern_id": "burglary_casing", "status": "escalate_ready", "distinct_senders": 5},
    },
    {
        "id": "identity-stripped",
        "title": "Identity stripped first",
        "community_id": OKE_ADO,
        "beat": "A resident describes behaviour, but also names an ethnic group. The name is removed before anything else reads the message.",
        "watch_for": "The behaviour survives (loitering, checking locks). The ethnic group and the word stranger do not.",
        "messages": [
            _m(6, 0, "A Hausa stranger was loitering by the gate at night, checking the locks on parked cars."),
        ],
        "expect": {"pattern_id": "burglary_casing", "redacted": True},
    },
    {
        "id": "yoruba",
        "title": "Same rules, in Yorùbá",
        "community_id": OKE_ADO,
        "beat": "Two residents text in Yorùbá, one with tone marks and one without. No language menu on a basic phone: the system reads the words.",
        "watch_for": "Both are read as Yorùbá. The word for stranger (àjèjì) and the ethnic group are stripped, and both still count toward the same burglary pattern.",
        "messages": [
            _m(12, 0, "Àjèjì kan ń rìn kiri ní òru, wọ́n ń wo ilé wa àti géètì."),
            _m(11, 0, "Okunrin Hausa kan n ya aworan ile ni adugbo wa lana."),
        ],
        "expect": {"pattern_id": "burglary_casing", "redacted": True, "locale": "yo"},
    },
    {
        "id": "neighbour-named",
        "title": "A neighbour is named",
        "community_id": OKE_ADO,
        "beat": "A message that accuses a named person instead of describing behaviour. This is how a rumour becomes a mob.",
        "watch_for": "It is refused with a reason a person can read, and it is never counted toward any pattern.",
        "messages": [
            _m(7, 0, "Mr Bello is a thief, someone should deal with him."),
        ],
        "expect": {"status": "rejected_targeting"},
    },
    {
        "id": "protected-line",
        "title": "The report nobody dares make",
        "community_id": OKE_ADO,
        "beat": "Reports about the people who guard the estate itself. In a WhatsApp group, the reporter's name is on it.",
        "watch_for": "Nothing appears on the committee desk. The second message used the ordinary line by mistake and is rerouted on its own.",
        "messages": [
            _m(8, 0, "The gateman on night duty let two men in through the side gate and shared the gate code.", line="safe"),
            _m(9, 0, "The Amotekun officer on night duty keeps extorting money from drivers at the gate."),
        ],
        "expect": {"protected_waiting": 2},
    },
    {
        "id": "weapon-fast-lane",
        "title": "Weapon: the fast lane",
        "community_id": OKE_ADO,
        "beat": "A gun is not a parked car. This pattern has its own, lower bar, set in a config file, not in code.",
        "watch_for": "One report is already a priority item on the desk. It still takes two different people, a day apart, to escalate. Never one.",
        "messages": [
            _m(10, 1, "Two men on a bike near the market junction, one of them was waving a gun."),
            _m(11, 0, "Heard gunshots behind the school and saw robbers running toward Adeoye street."),
        ],
        "expect": {"pattern_id": "weapon_sighting", "status": "escalate_ready", "distinct_senders": 2},
    },
    {
        "id": "second-community",
        "title": "Second community, new pattern",
        "community_id": BODIJA,
        "beat": "A different neighbourhood and a different kind of danger. Same engine. The community is one config row and the pattern is a keyword list.",
        "watch_for": "The view switches to Bodija Close 9. Nothing was deployed and no code changed.",
        "messages": [
            _m(1, 4, "Drums being offloaded at night at the warehouse, unmarked containers stacked inside."),
            _m(2, 3, "Strong smell of chemicals from the warehouse behind our close again this morning."),
            _m(3, 2, "Chemical drums stacked outside the fence, and some of them are leaking."),
            _m(4, 1, "Warehouse activity at night again, trucks with no plates offloading unmarked containers."),
            _m(5, 0, "Men carrying boxes marked blasting caps into the warehouse this evening."),
        ],
        "expect": {"pattern_id": "explosives_storage", "status": "escalate_ready", "distinct_senders": 5},
    },
    {
        "id": "profiling-guard",
        "title": "The profiling guard",
        "community_id": BODIJA,
        "beat": "Two reports meet the weapon bar, but both were about who someone is, not what they did.",
        "watch_for": "Escalation is blocked and held for a human review, because most of the reports needed identity redaction.",
        "messages": [
            _m(6, 1, "A foreigner who is not from this area was carrying a gun near the gate at night."),
            _m(7, 0, "An outsider was waving a gun at the market junction."),
        ],
        "expect": {"pattern_id": "weapon_sighting", "status": "escalate_blocked_profiling", "distinct_senders": 2},
    },
]

# One-click examples for the composer, so a live message can be typed in
# front of an audience without having to think of one.
CHIPS: List[Dict[str, str]] = [
    {"label": "Name an ethnic group", "line": "normal",
     "text": "A Hausa stranger was loitering by the gate at night, checking the locks on parked cars."},
    {"label": "Accuse a neighbour", "line": "normal",
     "text": "Mr Bello is a thief, someone should deal with him."},
    {"label": "Unrelated noise", "line": "normal",
     "text": "The generator next door was very loud again last night."},
    {"label": "Report the guards", "line": "safe",
     "text": "The gateman on night duty let two men in through the side gate."},
]


# ---------------------------------------------------------------------------
# presenter remote (served at /demo/remote)
# ---------------------------------------------------------------------------
#
# The console at /demo drives the story. The remote is its simpler sister:
# a list of ready-made messages, one click each, so a presenter can talk
# over the main screen and push in whichever message the story needs next.
# It sends through the same send_message() as the console, and the console
# and desk pages pick the message up live (see the BroadcastChannel wiring
# in the templates).
#
# Talking points are anchors for the presenter, not a script. They are
# shown on the remote only, never on the main screen.

TALKING_POINTS: Dict[str, List[str]] = {
    "street-speaks": [
        "Alone, each text sounds like nothing, so nobody posts it",
        "Senders on basic phones: night guards, okada riders, traders",
        "Watch at 3 people across 3 days, escalate at 5",
    ],
    "identity-stripped": [
        "Redaction runs before anything else reads the text",
        "The first person it protects is the innocent stranger",
        "A curfew makes 'stranger after curfew' the most common report",
    ],
    "yoruba": [
        "Language is detected from the words, no menu needed",
        "Tone marks or none, the same word lists match",
        "Identity words stripped in Yorùbá too, before anything reads it",
        "A new language is word lists in config, not code",
    ],
    "neighbour-named": [
        "This is how a rumour becomes a mob",
        "Refused, with a reason a person can read, and never counted",
        "No enforcement power, no public list, no public map",
    ],
    "protected-line": [
        "The credential, not a feature: residents can report the guards",
        "Threshold is 1, a whistleblower is alone by definition",
        "Goes to the landlord association, the desk never sees it",
        "Second message came in on the wrong line and was rerouted",
    ],
    "weapon-fast-lane": [
        "A gun is not a parked car: this pattern has its own bar",
        "One report is a priority watch at once",
        "Still two people, a day apart, to escalate. Never one",
    ],
    "second-community": [
        "New community is one config row, new danger is a keyword list",
        "Bodija, January 2024: explosives in an occupied house",
        "Neighbours lived beside it for weeks. Same engine",
    ],
    "profiling-guard": [
        "Most of these reports needed identity removed",
        "That is suspicion about a person, not observation of behaviour",
        "Held for a human review before anything moves",
    ],
}

# Extra messages for questions from the floor. They are not part of the
# scripted story, so they run in Bodija Close 9 or produce noise, and do
# not disturb the Oke-Ado burglary pattern the story builds up.
REMOTE_EXTRAS: List[Dict[str, Any]] = [
    {
        "id": "one-loud-voice",
        "title": "Q&A: one loud voice",
        "community_id": BODIJA,
        "beat": "One phone sends the same worry again and again.",
        "watch_for": "Three reports, one sender. The bar counts people, not texts, so it stays below threshold.",
        "talking_points": [
            "Senders are hashed, so repeats are counted once",
            "Fifteen texts from one phone are still one person",
        ],
        "messages": [
            _m(12, 2, "Strange vehicle parked outside the close again, engine running."),
            _m(12, 1, "Same strange vehicle parked outside, two men watching our house."),
            _m(12, 0, "The strange vehicle is parked outside again tonight."),
        ],
        "expect": {"pattern_id": "burglary_casing", "status": "below_threshold", "distinct_senders": 1},
    },
    {
        "id": "one-evening-burst",
        "title": "Q&A: a burst in one evening",
        "community_id": BODIJA,
        "beat": "Three different people report within the same evening.",
        "watch_for": "Three senders, but less than a day between them. The span rule keeps a panic from escalating itself.",
        "talking_points": [
            "Corroboration needs people and time",
            "A single scary evening is not yet a pattern",
        ],
        "messages": [
            _m(9, 0, "Someone was loitering by the close entrance tonight."),
            _m(10, 0, "A man was checking gates along the close this evening."),
            _m(11, 0, "Saw someone climbing the fence of the end house tonight."),
        ],
        "expect": {"pattern_id": "burglary_casing", "status": "below_threshold", "distinct_senders": 3},
    },
    {
        "id": "yoruba-accusation",
        "title": "Q&A: an accusation in Yorùbá",
        "community_id": OKE_ADO,
        "beat": "The same mob message as scene 4, in Yorùbá: a name, a label, a call to beat him.",
        "watch_for": "Refused with a readable reason, exactly like the English one.",
        "talking_points": [
            "The accusation guard reads every language on every message",
            "A wrong language guess can only over-protect, never let one through",
        ],
        "messages": [
            _m(7, 0, "Baba Bello je ole, e lu u."),
        ],
        "expect": {"status": "rejected_targeting"},
    },
    {
        "id": "everyday-noise",
        "title": "Q&A: everyday noise",
        "community_id": OKE_ADO,
        "beat": "The things people actually text about most days.",
        "watch_for": "Stored as noise and never counted, so they cannot inflate a real pattern.",
        "talking_points": [
            "Noise is kept for the record but never clusters",
            "Pattern definitions are data, so what counts is a community choice",
        ],
        "messages": [
            _m(1, 0, "The generator next door was very loud again last night."),
            _m(2, 0, "Our goat got lost near the junction, please call if you see it."),
            _m(3, 0, "Two neighbours were shouting at each other about the gutter."),
        ],
        "expect": {"noise": 3},
    },
]


# ---------------------------------------------------------------------------
# staged recording (seed/load_into_server.py --hold-last oke-ado-phase2)
# ---------------------------------------------------------------------------
#
# For a recording, the community should already sit at Watch with four
# senders, and the fifth should arrive live. The loader posts the first four
# street-speaks messages through /webhook/sms with these external ids. The
# remote sees them in the store, ticks them as sent, and makes the Yorùbá
# message (the yoruba scene's first) the live fifth, so the moment the bar
# tips to Ready also shows language detection and redaction.

STAGED_SCENE = "street-speaks"
STAGED_LIVE_FIFTH = ("yoruba", 0)  # (scene id, message index)


def _scene(scene_id: str) -> Dict[str, Any]:
    return next(s for s in SCENES if s["id"] == scene_id)


def staged_message_id(index: int) -> str:
    return f"stage-{STAGED_SCENE}-{index + 1}"


def staged_payloads(config, now=None) -> List[Dict[str, Any]]:
    """Webhook payloads for the first four street-speaks messages, dated
    relative to `now` exactly as the scene dates them."""
    scene = _scene(STAGED_SCENE)
    community = config.community_by_id(scene["community_id"])
    now = now or utcnow()
    return [
        {
            "id": staged_message_id(i),
            "to": community.normal_inbound,
            "from": _PHONE_BY_RESIDENT[m["resident"]],
            "text": m["text"],
            "date": (now - timedelta(days=m["days_ago"])).isoformat(),
        }
        for i, m in enumerate(scene["messages"][:-1])
    ]


def stage_token(store) -> Optional[str]:
    """The first staged report's store id if all four staged messages are in,
    else None. A fresh load gives a fresh id, so the remote can tell a new
    staged run from the one it already ticked."""
    count = len(_scene(STAGED_SCENE)["messages"]) - 1
    found = [store.find_report_by_external_id(staged_message_id(i)) for i in range(count)]
    return found[0].id if all(found) else None


def remote_groups(staged: bool = False) -> List[Dict[str, Any]]:
    """Message groups for the remote: the scripted scenes in order, then the
    Q&A extras. `expect` stays out, as it does for the console page.

    When `staged`, street-speaks ends with the Yorùbá message instead of its
    own fifth, and the yoruba scene no longer repeats it."""
    live_scene, live_index = STAGED_LIVE_FIFTH
    live = _scene(live_scene)["messages"][live_index]
    groups = []
    for scene in SCENES + REMOTE_EXTRAS:
        group = {k: v for k, v in scene.items() if k != "expect"}
        group.setdefault("talking_points", TALKING_POINTS.get(scene["id"], []))
        group["extra"] = scene in REMOTE_EXTRAS
        if staged and scene["id"] == STAGED_SCENE:
            group["messages"] = scene["messages"][:-1] + [live]
            group["watch_for"] = (
                "Four senders are already in, so the bar sits at Watch. The fifth arrives "
                "live, in Yorùbá: read as Yorùbá, the stranger word stripped, and the bar tips to Ready."
            )
        elif staged and scene["id"] == live_scene:
            group["messages"] = [m for i, m in enumerate(scene["messages"]) if i != live_index]
        groups.append(group)
    return groups


def remote_presend(staged: bool) -> List[str]:
    """Remote tick keys (group id:index) for messages already in the store."""
    if not staged:
        return []
    return [f"{STAGED_SCENE}:{i}" for i in range(len(_scene(STAGED_SCENE)["messages"]) - 1)]


def presenter_numbers(config) -> Dict[str, Any]:
    """The numbers a presenter quotes, read from config rather than typed
    into the page, so the crib sheet cannot disagree with the rules."""
    community = config.community_by_id(OKE_ADO) or next(iter(config.communities.values()))
    watch, escalate = clustering.resolve_thresholds(community, None)
    weapon = next((p for p in config.patterns if p.id == "weapon_sighting"), None)
    w_watch, w_escalate = clustering.resolve_thresholds(community, weapon)
    return {
        "watch": _threshold_view(watch),
        "escalate": _threshold_view(escalate),
        "weapon_watch": _threshold_view(w_watch),
        "weapon_escalate": _threshold_view(w_escalate),
        "profiling_pct": int(round(community.thresholds.profiling_guard_max_redacted_fraction * 100)),
    }


class DemoError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------

def _threshold_view(t) -> Dict[str, int]:
    return {"senders": t.min_distinct_senders, "days": t.min_span_days}


def _cluster_view(cluster, community, config, reports_by_id) -> Dict[str, Any]:
    pattern_def = next((p for p in config.patterns if p.id == cluster.pattern_id), None)
    watch, escalate = clustering.resolve_thresholds(community, pattern_def)
    members = [reports_by_id[rid] for rid in cluster.report_ids if rid in reports_by_id]
    redacted = sum(1 for r in members if r.was_redacted)
    return {
        "pattern_id": cluster.pattern_id,
        "pattern_name": pattern_def.name if pattern_def else cluster.pattern_id.replace("_", " "),
        "high_signal": cluster.high_signal,
        "status": cluster.status,
        "distinct_senders": cluster.distinct_senders,
        "report_count": len(cluster.report_ids),
        "span_days": round(cluster.span_days, 1),
        "watch": _threshold_view(watch),
        "escalate": _threshold_view(escalate),
        "redacted_count": redacted,
        "redacted_fraction": round(cluster.profiling.redacted_fraction, 2),
        "profiling_max": community.thresholds.profiling_guard_max_redacted_fraction,
        "profiling_fired": bool(cluster.profiling.fired),
        "first_date": cluster.first_report_at.date().isoformat(),
        "last_date": cluster.last_report_at.date().isoformat(),
    }


def _normal_clusters(ctx, community):
    reports = ctx.store.reports_for_community(community.id, channel="normal")
    already = {
        e.pattern_id: e.decided_at
        for e in ctx.store.audit_log_for_community(community.id)
        if e.action == "escalate"
    }
    clusters = clustering.compute_clusters(
        reports, community, already_escalated=already, patterns=ctx.config.patterns
    )
    return reports, clusters


def _days_ago(dt) -> int:
    return max(0, (utcnow().date() - dt.astimezone(utcnow().tzinfo).date()).days)


def build_state(ctx, community) -> Dict[str, Any]:
    """Everything the signal board draws, for one community.

    Normal-channel data only, at day granularity, with no sender identity.
    The protected inbox is reported as counts and nothing else.
    """
    with ctx.lock:
        reports, clusters = _normal_clusters(ctx, community)
        protected = ctx.store.reports_for_community(community.id, channel="protected")
        audit = ctx.store.audit_log_for_community(community.id)
        protected_items = clustering.protected_items(
            protected,
            community,
            already_escalated_report_ids={
                e.evidence_report_ids[0]: e.decided_at for e in audit if e.action == "protected_escalate"
            },
        )

    reports_by_id = {r.id: r for r in reports}
    patterns = {p.id: p for p in ctx.config.patterns}

    feed = []
    for r in sorted(reports, key=lambda r: r.received_at, reverse=True):
        if r.status != "stored" or r.pattern_id == "unclassified":
            continue
        feed.append({
            "text": r.redacted_text,
            "pattern_name": patterns[r.pattern_id].name if r.pattern_id in patterns else r.pattern_id,
            "date": r.received_at.date().isoformat(),
            "days_ago": _days_ago(r.received_at),
            "was_redacted": r.was_redacted,
        })
        if len(feed) >= 12:
            break

    escalations = [
        {
            "pattern_name": patterns[e.pattern_id].name if e.pattern_id in patterns else e.pattern_id,
            "decided_by": e.decided_by,
            "date": e.decided_at.date().isoformat(),
        }
        for e in audit
        if e.channel == "normal" and e.action == "escalate"
    ]

    return {
        "community": {
            "id": community.id,
            "name": community.name,
            "normal_inbound": community.normal_inbound,
            "protected_inbound": community.protected_inbound,
        },
        "clusters": [_cluster_view(c, community, ctx.config, reports_by_id) for c in clusters],
        "feed": feed,
        "counts": {
            "noise": sum(1 for r in reports if r.status == "stored" and r.pattern_id == "unclassified"),
            "refused": sum(1 for r in reports if r.status == "rejected_targeting"),
            "total": len(reports),
        },
        "escalations": escalations,
        # Counts only. The text of a protected report is never part of this payload.
        "protected_inbox": {
            "waiting": sum(1 for i in protected_items if i.status != clustering.PROTECTED_ESCALATED),
            "escalated": sum(1 for i in protected_items if i.status == clustering.PROTECTED_ESCALATED),
        },
    }


def send_message(ctx, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Send one demo message through the real webhook path and describe what
    the pipeline did with it, step by step, for the console's trace panel.
    """
    community = ctx.config.community_by_id(str(spec.get("community_id", "")))
    if community is None:
        raise DemoError(404, "unknown community")

    line = spec.get("line", "normal")
    if line not in ("normal", "safe"):
        raise DemoError(400, "line must be 'normal' or 'safe'")

    try:
        resident = int(spec.get("resident"))
    except (TypeError, ValueError):
        raise DemoError(400, "unknown resident")
    phone = _PHONE_BY_RESIDENT.get(resident)
    if phone is None:
        raise DemoError(400, "unknown resident")

    text = str(spec.get("text") or "").strip()
    if not text:
        raise DemoError(400, "message text is empty")
    if len(text) > MAX_TEXT_LENGTH:
        raise DemoError(400, f"message is longer than {MAX_TEXT_LENGTH} characters")

    try:
        days_ago = float(spec.get("days_ago") or 0)
    except (TypeError, ValueError):
        raise DemoError(400, "days_ago must be a number")
    days_ago = min(max(days_ago, 0.0), float(MAX_DAYS_AGO))

    to = community.protected_inbound if line == "safe" else community.normal_inbound
    received_at = utcnow() - timedelta(days=days_ago)
    payload = {
        "id": f"demo-{uuid.uuid4().hex}",
        "to": to,
        "from": phone,
        "text": text,
        "date": received_at.isoformat(),
    }

    drain = getattr(ctx.llm, "drain_events", None)
    with ctx.lock:
        if drain:
            drain()  # start this message with a clean slate
        _, before = _normal_clusters(ctx, community)
        report = ingest.receive_webhook(payload, ctx.config, ctx.llm, ctx.store)
        reports_after, after = _normal_clusters(ctx, community)
        events = drain() if drain else []
    # Which reader handled the message, and any fallback or floor catch.
    # Plain-language notes only: no message content, safe on either channel.
    reader = {
        "name": "Claude" if getattr(ctx.llm, "backend_name", "") == "claude" else "rule-based lists",
        "model": getattr(ctx.llm, "model_name", "") or None,
        "events": events,
    }

    if report is None:
        return {"processed": False, "note": "Logged for retry. The message is not lost.", "reader": reader}

    result: Dict[str, Any] = {
        "processed": True,
        "to": to,
        "line": line,
        "sender_hash_short": report.sender_hash[:10],
        "status": report.status,
        "channel": report.channel,
        "rerouted": line == "normal" and report.channel == "protected",
        "date": received_at.date().isoformat(),
        "locale": report.locale_detected,
        "locale_name": ctx.config.locale_names.get(report.locale_detected, report.locale_detected),
        "reader": reader,
    }

    if report.channel == "protected":
        # The sender knows what they wrote. The trace does not repeat it, and
        # does not say what the system made of it: that is the protected
        # inbox's business, not the console's.
        return result

    pattern_def = next((p for p in ctx.config.patterns if p.id == report.pattern_id), None)
    result.update({
        "redacted_text": report.redacted_text,
        "categories_redacted": report.categories_redacted,
        "pattern_id": report.pattern_id,
        "pattern_name": pattern_def.name if pattern_def else None,
        "pattern_score": report.pattern_score,
        "rejection_reason": report.rejection_reason,
        "cluster": None,
        "previous_status": None,
    })

    if report.status == "stored" and report.pattern_id != "unclassified":
        reports_by_id = {r.id: r for r in reports_after}
        now_cluster = next((c for c in after if c.pattern_id == report.pattern_id), None)
        was_cluster = next((c for c in before if c.pattern_id == report.pattern_id), None)
        if now_cluster is not None:
            result["cluster"] = _cluster_view(now_cluster, community, ctx.config, reports_by_id)
        result["previous_status"] = was_cluster.status if was_cluster else None
    return result


def reset(ctx) -> None:
    with ctx.lock:
        ctx.store.reset_all()
