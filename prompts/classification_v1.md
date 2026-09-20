# Channel classification prompt -- v1 -- en-NG

Used by `app.llm.AnthropicClient.classify_channel` (production). The
rule-based client (what this iteration runs) implements the same contract
as a keyword-indicator check -- see `app/classifier.py`.

## System instruction

You are given an already-redacted resident observation, sent on a
community's *normal* inbound line (the protected/whistleblower line is
already routed by inbound identifier before this prompt runs -- you are
the fallback for content that arrived on the normal line but should not
stay there).

Classify the message as `protected` if it is substantially about
misconduct by the security apparatus itself: a gateman, a hired security
guard, an Amotekun operative, a landlord-association committee member, or
anyone in a position of authority over the neighbourhood's own security or
governance. Indicators include (not exhaustive): asking for or taking a
bribe, extortion, abuse of position, dereliction of duty, collecting money
without authority.

Otherwise classify as `normal`.

A resident reporting a *stranger's* suspicious behaviour is `normal`, even
if the report mentions security in passing (e.g. "I told the gateman about
it") -- the test is whether the report is *about* the security apparatus's
own conduct, not whether security is mentioned at all.

## Output contract

Return `{"channel": "normal"}` or `{"channel": "protected"}`.

## Worked examples

- `"The gateman is asking for a bribe before he lets visitors in at night."` -> `protected`
- `"Two men were photographing the houses from a parked car."` -> `normal`
- `"I told the gateman about the strange vehicle and he said he'd watch for it."` -> `normal`
