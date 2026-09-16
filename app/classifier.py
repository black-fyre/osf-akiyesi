"""Channel classifier (CLAUDE.md component 3): normal or protected.

Two signals, checked in order:

1. Which inbound identifier the message arrived on (config: a community's
   normal_inbound vs protected_inbound -- a resident who deliberately texts
   the "SAFE" keyword is choosing the protected channel regardless of what
   they write).
2. A content fallback: if a resident uses the normal line but the message
   is clearly about the security apparatus itself (a gateman, a hired
   guard, a committee member), route it to the protected channel anyway,
   because that is exactly the report a normal-channel, non-anonymous group
   chat cannot safely carry.

Both signals are config-driven (the inbound identifiers live in
communities.yaml, the indicator vocabulary would live in a
protected_indicators section of redaction_terms.yaml-style config) so
tuning the fallback for a new community or language is not a code change.
"""
from __future__ import annotations

from app.config import AppConfig, Community
from app.llm import LLMClient

# Kept small and inline (rather than its own config file) since it is a
# single flat list with no per-community variation yet; promote to a
# config/ file the moment a second community needs a different list.
_PROTECTED_INDICATOR_TERMS_EN = [
    "gateman",
    "gate man",
    "security guard",
    "amotekun officer",
    "amotekun operative",
    "committee member",
    "landlord chairman",
    "asking for bribe",
    "asked for a bribe",
    "extort",
    "extorting",
    "abusing his position",
    "abusing her position",
]


def classify_channel(
    inbound_identifier: str,
    redacted_text: str,
    community: Community,
    config: AppConfig,
    llm: LLMClient,
) -> str:
    channel_from_inbound = config.channel_for_inbound(community, inbound_identifier)
    if channel_from_inbound == "protected":
        return "protected"

    # Content fallback only applies to English for now (locale stub only
    # covers en-NG's indicator list); non-English falls back to the
    # inbound-identifier signal alone.
    if community.locale == "en-NG":
        return llm.classify_channel(redacted_text, _PROTECTED_INDICATOR_TERMS_EN)

    return "normal"
