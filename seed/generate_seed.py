#!/usr/bin/env python3
"""Deterministically generates seed/reports.json and
seed/bodija_scale_replay.json.

Re-run with `python3 seed/generate_seed.py` after changing the scenario
below; the output is checked in, so running this is optional unless the
scenario changes. Every report is synthetic; no real person, real named
resident, or real phone number appears anywhere in this file.

Scenario composition (see CLAUDE.md "Seed data"):
  - weak signals that cluster into one real pattern -> oke-ado-phase2 burglary_casing,
    8 distinct senders over ~29 days: crosses watch at sender 3, escalate at sender 5.
  - a profiling-cascade cluster -> bodija-close-9 burglary_casing, 6 distinct senders,
    4 of them phrased with identity/stranger markers (67% redacted, over the 60%
    profiling-guard threshold) so it reaches escalate corroboration but is held for
    manual review instead of auto-escalating.
  - a near-miss -> oke-ado-phase2 explosives_storage, 2 distinct senders: never
    reaches the 3-sender watch floor.
  - ambient noise -> goats, loud music, generator complaints: scores 0 against every
    pattern, filed as unclassified, never clusters.
  - adversarial reports naming a neighbour -> caught by the targeting guard,
    status=rejected_targeting, excluded from clustering.
  - protected-channel reports about the security apparatus itself (a gateman, an
    Amotekun operative, a committee member, a landlord chairman) -> routed to the
    landlord association, threshold 1; one of them also trips the profiling guard.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
BASE_DATE = datetime(2026, 1, 5, 7, 0, 0, tzinfo=timezone.utc)  # day 0 of the six-week window

OKE_ADO_NORMAL = "40404*REPORT-OKEADO2"
OKE_ADO_PROTECTED = "40404*SAFE-OKEADO2"
BODIJA_NORMAL = "40404*REPORT-BODIJA9"
BODIJA_PROTECTED = "40404*SAFE-BODIJA9"


def day(offset: int, hour: int = 21, minute: int = 0) -> str:
    return (BASE_DATE + timedelta(days=offset, hours=hour - 7, minutes=minute)).isoformat()


def phone(prefix: str, n: int) -> str:
    return f"+234801{prefix}{n:04d}"


def msg(mid: str, to: str, sender: str, text: str, offset_day: int, hour: int = 21, minute: int = 0) -> dict:
    return {"id": mid, "to": to, "from": sender, "text": text, "date": day(offset_day, hour, minute)}


def build_main_scenario() -> list:
    reports = []

    # --- oke-ado-phase2: clean burglary_casing cluster, 8 distinct senders ---
    clean_senders = [phone("1", i) for i in range(1, 9)]
    clean_texts = [
        "Saw a strange vehicle parked outside the empty plot on Alade Street for over an hour.",
        "Men were unloading sacks into the unfinished building near Alade Street around 9pm.",
        "Someone was checking gates along Alade Street block by block late last night.",
        "Noticed a person testing the gate at the empty house on Alade Street.",
        "A car was loitering near the junction on Alade Street twice this week.",
        "Watched two men photographing the houses on Alade Street from a parked car.",
        "Someone was seen climbing the fence behind Alade Street in the early hours.",
        "A group was counting houses along Alade Street, seemed to be casing the row.",
    ]
    offsets = [1, 4, 7, 10, 14, 18, 23, 29]
    for i, (sender, text, off) in enumerate(zip(clean_senders, clean_texts, offsets), start=1):
        reports.append(msg(f"okeado-clean-{i}", OKE_ADO_NORMAL, sender, text, off))
    # Follow-up messages from existing senders (padding volume, not distinct-sender count)
    followups = [
        (clean_senders[0], "Same strange vehicle was parked outside the empty plot again tonight.", 20),
        (clean_senders[1], "More sacks were unloaded into the same unfinished building this week.", 25),
        (clean_senders[2], "Gate-checking behaviour on Alade Street again, same pattern as before.", 27),
        (clean_senders[4], "The loitering car came back to the junction a third time.", 31),
        (clean_senders[3], "Another gate along Alade Street was tested overnight.", 33),
        (clean_senders[5], "The men photographing houses were seen again, different car this time.", 35),
        (clean_senders[6], "Fence-climbing behind Alade Street reported again by a second household.", 36),
        (clean_senders[7], "Another count of houses along the row, same casing pattern as before.", 38),
    ]
    for i, (sender, text, off) in enumerate(followups, start=1):
        reports.append(msg(f"okeado-clean-followup-{i}", OKE_ADO_NORMAL, sender, text, off))

    # --- oke-ado-phase2: near miss, explosives_storage, only 2 distinct senders ---
    near_miss_senders = [phone("2", 1), phone("2", 2)]
    near_miss_texts = [
        "There were unmarked containers behind the old warehouse on Property Row.",
        "A strong smell of chemicals came from the shed near the water tank.",
        "More unmarked containers arrived behind the old warehouse again this week.",
        "Another strong smell of chemicals from the shed again tonight.",
    ]
    near_miss_offsets = [2, 30, 34, 40]
    near_miss = list(zip(
        [near_miss_senders[i % 2] for i in range(4)],
        near_miss_texts,
        near_miss_offsets,
    ))
    for i, (sender, text, off) in enumerate(near_miss, start=1):
        reports.append(msg(f"okeado-nearmiss-{i}", OKE_ADO_NORMAL, sender, text, off))

    # --- oke-ado-phase2: ambient noise, must not cluster ---
    noise_oke_ado = [
        (phone("3", 1), "Someone's goat keeps escaping and eating flowers on our street, please can the owner fence it.", 3),
        (phone("3", 2), "Loud music from a party went on till 1am again, residents are complaining.", 9),
        (phone("3", 3), "There was a shouting argument between two neighbours over a parking spot this morning.", 16),
        (phone("3", 4), "Please can someone fix the generator noise every night, it is disturbing sleep.", 22),
        (phone("3", 5), "Refuse bin was not collected again this week on our row.", 28),
        (phone("3", 6), "The goat is back again, now it has eaten someone's washing off the line.", 32),
        (phone("3", 7), "Another loud party till late, please can the association send a reminder.", 37),
        (phone("3", 8), "Pothole on the close is getting worse after the rain.", 11),
        (phone("3", 9), "Street light at the corner has been out for two weeks now.", 24),
        (phone("3", 10), "Two traders had a disagreement over stall space near the entrance.", 39),
    ]
    for i, (sender, text, off) in enumerate(noise_oke_ado, start=1):
        reports.append(msg(f"okeado-noise-{i}", OKE_ADO_NORMAL, sender, text, off))

    # --- oke-ado-phase2: adversarial, targeting a named neighbour ---
    adversarial_oke_ado = [
        (phone("4", 1), "Chidi Okoro is a thief, everyone should avoid his shop.", 6),
        (phone("4", 2), "Musa Danladi is a criminal and should be dealt with.", 19),
        (phone("4", 3), "Peter Adeyemi is a fraudster, do not do business with him.", 34),
        (phone("4", 4), "Grace Umeh is a bad person, chase her out of the estate.", 41),
    ]
    for i, (sender, text, off) in enumerate(adversarial_oke_ado, start=1):
        reports.append(msg(f"okeado-adversarial-{i}", OKE_ADO_NORMAL, sender, text, off))

    # --- oke-ado-phase2: protected channel ---
    protected_oke_ado = [
        (phone("5", 1), "The gateman is asking for a bribe before he lets visitors in at night.", 5),
        (phone("5", 2), "One of the Amotekun operatives has been extorting okada riders at the checkpoint.", 17),
        (phone("5", 3), "A committee member collected money from a trader and never returned it.", 26),
        (phone("5", 4), "The gateman let his friends in without checking anyone for two nights running.", 33),
        (phone("5", 5), "Committee member is asking residents for money outside the approved levy.", 40),
        (phone("5", 6), "Amotekun operative was seen drinking on duty at the gate post last night.", 21),
    ]
    for i, (sender, text, off) in enumerate(protected_oke_ado, start=1):
        reports.append(msg(f"okeado-protected-{i}", OKE_ADO_PROTECTED, sender, text, off))

    # --- bodija-close-9: profiling-cascade cluster, burglary_casing ---
    profiling_senders = [phone("6", i) for i in range(1, 5)]
    profiling_texts = [
        "A Fulani stranger was seen checking gates along our close late at night.",
        "Someone who is not from this area was loitering near the compound entrance.",
        "A stranger was testing the gate of the empty house, said he spoke with an accent.",
        "An outsider was seen unloading sacks into the unfinished building by the close.",
    ]
    profiling_offsets = [2, 6, 10, 15]
    for i, (sender, text, off) in enumerate(zip(profiling_senders, profiling_texts, profiling_offsets), start=1):
        reports.append(msg(f"bodija-profiling-{i}", BODIJA_NORMAL, sender, text, off))

    clean_bodija_senders = [phone("6", 5), phone("6", 6)]
    clean_bodija_texts = [
        "Two men were photographing the houses along our close from a parked car.",
        "Someone was climbing the fence behind the close in the early hours.",
    ]
    clean_bodija_offsets = [18, 22]
    for i, (sender, text, off) in enumerate(zip(clean_bodija_senders, clean_bodija_texts, clean_bodija_offsets), start=1):
        reports.append(msg(f"bodija-clean-{i}", BODIJA_NORMAL, sender, text, off))

    # --- bodija-close-9: ambient noise ---
    noise_bodija = [
        (phone("7", 1), "The generator at the corner house is too loud every night this week.", 4),
        (phone("7", 2), "Two neighbours were arguing loudly about a fence boundary again.", 12),
        (phone("7", 3), "A stray dog has been going through bins on our close, can someone help.", 20),
        (phone("7", 4), "Water tanker blocked the close entrance for over an hour this morning.", 28),
        (phone("7", 5), "Another argument over a parking spot near the close junction.", 33),
        (phone("7", 6), "The generator noise complaint again, still not resolved.", 39),
        (phone("7", 7), "A cat has been getting into bins on the close all week.", 8),
        (phone("7", 8), "Drainage by the close entrance needs clearing before the rains.", 30),
    ]
    for i, (sender, text, off) in enumerate(noise_bodija, start=1):
        reports.append(msg(f"bodija-noise-{i}", BODIJA_NORMAL, sender, text, off))

    # --- bodija-close-9: adversarial ---
    adversarial_bodija = [
        (phone("8", 1), "Blessing Nwachukwu is a witch, mob justice for her if she is seen again.", 24),
        (phone("8", 2), "Emeka Obi is a kidnapper, burn his house down.", 36),
    ]
    for i, (sender, text, off) in enumerate(adversarial_bodija, start=1):
        reports.append(msg(f"bodija-adversarial-{i}", BODIJA_NORMAL, sender, text, off))

    # --- bodija-close-9: protected channel (one trips the profiling guard) ---
    protected_bodija = [
        (phone("9", 1), "The security guard sleeps on duty and let a stranger walk in unchallenged last week.", 11),
        (phone("9", 2), "Landlord chairman is abusing his position to allocate extra plots to his relatives.", 27),
        (phone("9", 3), "Gateman at the close entrance was seen taking money to let a vehicle skip the log book.", 35),
        (phone("9", 4), "Committee member threatened a resident who asked for the levy account statement.", 41),
    ]
    for i, (sender, text, off) in enumerate(protected_bodija, start=1):
        reports.append(msg(f"bodija-protected-{i}", BODIJA_PROTECTED, sender, text, off))

    reports.sort(key=lambda r: r["date"])
    return reports


def build_bodija_scale_replay() -> list:
    """Illustrates the scale claim in CLAUDE.md: same pipeline, a different
    pattern definition (explosives_storage instead of burglary_casing),
    reusing the bodija-close-9 community. Dated across the six weeks
    leading up to 16 January 2024, the real date of the Bodija explosives
    incident, so seed/replay.py can report how many days before the
    incident the corroboration threshold would have been crossed. This is
    a scale-slide illustration, not the live demo (CLAUDE.md: "Bodija goes
    on the scale slide, not in the demo").
    """
    incident_date = datetime(2024, 1, 16, 12, 0, 0, tzinfo=timezone.utc)
    window_start = incident_date - timedelta(days=42)

    def d(offset_day: int, hour: int = 20) -> str:
        return (window_start + timedelta(days=offset_day, hours=hour)).isoformat()

    senders = [phone("e", i) for i in range(1, 7)]
    texts = [
        "Drums being offloaded behind the compound wall again last night.",
        "Strong smell of chemicals coming from the boys' quarters at the back of the house.",
        "Unmarked containers keep arriving late at night, offloaded quickly by two men.",
        "Warehouse activity at night has picked up, generator running till morning.",
        "More chemical drums moved in through the back gate this week.",
        "Neighbours noticed unmarked containers stacked behind the fence again.",
    ]
    offsets = [3, 9, 16, 24, 31, 37]  # all well before day 42 (the incident)
    reports = []
    for i, (sender, text, off) in enumerate(zip(senders, texts, offsets), start=1):
        reports.append({
            "id": f"bodija-scale-{i}",
            "to": BODIJA_NORMAL,
            "from": sender,
            "text": text,
            "date": d(off),
        })
    reports.append({"_incident_date": incident_date.isoformat(), "_note": "16 Jan 2024 Bodija explosives incident; not itself a report"})
    return reports


if __name__ == "__main__":
    main_scenario = build_main_scenario()
    (OUT_DIR / "reports.json").write_text(json.dumps(main_scenario, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(main_scenario)} reports to seed/reports.json")

    bodija_scale = build_bodija_scale_replay()
    (OUT_DIR / "bodija_scale_replay.json").write_text(json.dumps(bodija_scale, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(bodija_scale) - 1} reports + incident marker to seed/bodija_scale_replay.json")
