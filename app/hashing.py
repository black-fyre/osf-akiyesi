"""Sender hashing (CLAUDE.md design rule #7: anonymity by default).

No phone number is stored in plaintext beside report content. The sender is
reduced to a salted hash, stable enough to dedupe and rate-limit repeat
senders, useless for recovering the original number without the salt.
"""
from __future__ import annotations

import hashlib
import os

# In production this MUST be set to a long random value and kept out of
# version control (see .env.example). A fixed fallback is used here only so
# the demo and test suite are reproducible without extra setup -- it is not
# a secret in this repo's threat model, since the point of the salt is
# irreversibility of casual inspection, not defence against a determined
# attacker with database access.
_DEFAULT_SALT = "akiyesi-demo-salt-change-me-in-deployment"


def hash_sender(phone_number: str, salt: str | None = None) -> str:
    """Return a stable, irreversible identifier for a phone number.

    Same number -> same hash (needed for corroboration-by-distinct-sender
    and for rate limiting). The hash never appears next to the raw number
    in storage; callers should discard the raw number immediately after
    hashing it.
    """
    salt = salt if salt is not None else os.environ.get("AKIYESI_SENDER_SALT", _DEFAULT_SALT)
    normalized = "".join(ch for ch in phone_number.strip() if ch.isdigit() or ch == "+")
    digest = hashlib.sha256(f"{salt}:{normalized}".encode("utf-8")).hexdigest()
    return digest[:24]
