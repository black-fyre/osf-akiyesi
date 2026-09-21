"""Pipeline orchestration: redact -> targeting guard -> classify -> extract
-> store.

app/ingest.py calls process_inbound() once per inbound message (whether it
arrived via the real SMS webhook or the /simulate/inbound demo endpoint).
Everything here is deliberately synchronous and side-effect-explicit so it
is easy to unit test stage by stage as well as end to end.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from app.classifier import classify_channel
from app.config import AppConfig, Community
from app.extraction import extract
from app.hashing import hash_sender
from app.llm import LLMClient
from app.locale_detect import detect_locale
from app.models import Report, utcnow
from app.redaction import redact_report_text
from app.storage import Store
from app.targeting_guard import check_named_target_accusation

STATUS_STORED = "stored"
STATUS_REJECTED_TARGETING = "rejected_targeting"
STATUS_NEEDS_REVIEW_LOCALE = "needs_review_locale"

SUPPORTED_LOCALES = {"en-NG", "yo"}

# One pool for the process rather than one per message: the channel call
# runs here while extraction runs on the request thread. Sized for a few
# messages arriving at once on the threaded server.
_READERS = ThreadPoolExecutor(max_workers=8, thread_name_prefix="akiyesi-reader")


class UnknownInboundError(ValueError):
    pass


class MissingFieldError(ValueError):
    pass


@dataclass(frozen=True)
class InboundPayload:
    to: str
    sender_hash: str  # salted hash of the sender's phone number; the number itself is never kept
    text: str
    external_message_id: Optional[str]
    locale_hint: Optional[str]
    received_at: datetime


def parse_payload(raw: Dict[str, Any]) -> InboundPayload:
    to = raw.get("to") or raw.get("destination") or raw.get("shortCode")
    sender = raw.get("from") or raw.get("sender")
    text = raw.get("text") or raw.get("message")
    # app/ingest.py swaps the phone number for its hash before a payload is
    # logged or processed, so a retried payload arrives here already hashed.
    # Payloads handed straight to process_inbound (tests, seed replay) still
    # carry the number, which is hashed here and goes no further.
    sender_hash = raw.get("sender_hash") or (hash_sender(str(sender)) if sender else None)
    missing = [name for name, value in (("to", to), ("from", sender_hash), ("text", text)) if not value]
    if missing:
        # Names the missing fields only. Never echo the payload: this message
        # is stored in inbound_log.error, and the payload holds the sender
        # and the original text.
        raise MissingFieldError(f"payload missing required field(s): {', '.join(missing)}")

    received_at = utcnow()
    if raw.get("date"):
        try:
            received_at = datetime.fromisoformat(raw["date"])
        except ValueError:
            pass  # keep utcnow() -- a malformed date must not crash ingest

    return InboundPayload(
        to=str(to),
        sender_hash=str(sender_hash),
        text=str(text),
        external_message_id=raw.get("id"),
        locale_hint=raw.get("locale"),
        received_at=received_at,
    )


def process_inbound(raw_payload: Dict[str, Any], config: AppConfig, llm: LLMClient, store: Store) -> Report:
    payload = parse_payload(raw_payload)

    if payload.external_message_id:
        existing = store.find_report_by_external_id(payload.external_message_id)
        if existing is not None:
            return existing  # idempotent replay / retry

    community = config.community_by_inbound(payload.to)
    if community is None:
        raise UnknownInboundError(f"no community configured for inbound identifier {payload.to!r}")

    # Per-message language (app/locale_detect.py): the payload's hint, else
    # detection from the words used, else the community default.
    effective_locale = detect_locale(payload.text, community.locale, config, hint=payload.locale_hint)
    locale_supported = effective_locale in SUPPORTED_LOCALES
    # Pattern matching reads the detected language plus the community's.
    locales = [effective_locale] + ([community.locale] if community.locale != effective_locale else [])
    # The safety layers read every language, whatever was detected. A
    # code-switched "Ajeji kan was loitering by the gate" is detected as
    # English, and must still lose "Ajeji" (a test caught exactly this).
    safety_locales = config.all_locales(first=locales)

    redacted = redact_report_text(payload.text, safety_locales, config, llm)

    status = STATUS_STORED
    rejection_reason: Optional[str] = None

    if not locale_supported:
        status = STATUS_NEEDS_REVIEW_LOCALE
        rejection_reason = (
            f"locale {effective_locale!r} is not in SUPPORTED_LOCALES {sorted(SUPPORTED_LOCALES)}; "
            "stored for manual review rather than discarded, and excluded from clustering "
            "until reviewed."
        )

    # Channel and pattern both read only the redacted text, so with Claude
    # as the reader the two calls run at the same time rather than back to
    # back (about a second and a half saved per message).
    pending_channel = _READERS.submit(
        classify_channel, payload.to, redacted.text, community, config, llm, locales=safety_locales
    )
    extraction = extract(redacted.text, community, config, llm, locales=locales)
    channel = pending_channel.result()

    guard = check_named_target_accusation(redacted.text, safety_locales, config)
    if guard.blocked and status == STATUS_STORED:
        status = STATUS_REJECTED_TARGETING
        rejection_reason = guard.reason

    report = Report(
        id=store.new_id(),
        external_message_id=payload.external_message_id,
        community_id=community.id,
        channel=channel,
        sender_hash=payload.sender_hash,
        redacted_text=redacted.text,
        categories_redacted=redacted.categories_redacted,
        pattern_id=extraction.pattern_id,
        pattern_score=extraction.pattern_score,
        time_of_day=extraction.time_of_day,
        received_at=payload.received_at,
        status=status,
        rejection_reason=rejection_reason,
        locale_detected=effective_locale,
    )
    store.save_report(report)
    return report
