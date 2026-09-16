# Àkíyèsí

*(Yoruba: "observation / taking notice")*

A community early-warning aggregation system, built for the Andela x Open
Society Foundations hackathon ("Information you can trust"). Residents send
observations by SMS from any phone, including feature phones. A redaction
layer strips identity content before anything else sees it; weak,
individually-unremarkable observations are then clustered into a
corroborated pattern a neighbourhood security committee can act on -- never
a single report acted on alone. A separate, anonymous protected channel
lets residents report the security apparatus itself (a gateman, a hired
guard, a committee member).

The full brief this implements is [`CLAUDE.md`](./CLAUDE.md) at the repo
root. This README covers what's actually built and how to run it; see
[`docs/ai-usage.md`](./docs/ai-usage.md) for how it was built.

## Why this isn't "just Ushahidi"

Ushahidi (2008-) collects incident reports and publishes them to a public
map. This deliberately does neither: it aggregates signals too weak to be
worth reporting individually, strips identity content before an LLM ever
sees the text, and never produces a public map, list, or feed. No
enforcement power, no public accusations -- a structured referral brief to
the community's own security committee (and, for the protected channel,
the landlord association) is the only output.

## What's implemented

All six components CLAUDE.md scopes, plus the audit trail, referral
briefs, and a profiling guard, are built and tested:

1. **Ingest** -- `app/ingest.py`, `app/pipeline.py`. An SMS-webhook-shaped
   endpoint (`POST /webhook/sms`) and a demo-reliability endpoint
   (`POST /simulate/inbound`, identical handling). A dropped/crashed
   webhook is durably logged before processing starts and can be retried
   (`POST /ingest/retry` or `app.ingest.retry_pending`) without duplicating
   an already-stored report.
2. **Redaction** -- `app/redaction.py`, config-driven off
   `config/redaction_terms.yaml`. Strips nationality, ethnicity/tribe,
   religion, and stranger-or-foreigner markers *before* anything
   downstream sees the text; only the redacted text is ever persisted.
3. **Channel classifier** -- `app/classifier.py`. Routes by which inbound
   identifier a message arrived on, with a content-based fallback so a
   report about the security apparatus itself is treated as protected even
   if sent on the normal line.
4. **Clustering with corroboration threshold** -- `app/clustering.py`.
   Normal channel: 3 distinct senders / 3+ days = watch, 5 / 3+ days =
   escalate-ready. Protected channel: threshold 1, uncorroborated by
   design. All values in `config/thresholds.yaml`.
5. **Verification desk** -- `app/server.py` + `app/templates/`.
   Server-side Jinja2 templates, no JS framework. Lists clusters, shows a
   referral brief, escalate action, audit log. Never queries protected-
   channel reports at all, and never renders a timestamp finer than a day.
6. **Profiling guard** -- `app/profiling_guard.py`. Flags any cluster
   (normal or protected) where over 60% of its reports needed identity
   redaction, and blocks escalation pending manual review.

Also built, not in the six but load-bearing for the required tests: a
**named-target accusation guard** (`app/targeting_guard.py`) that catches
a report naming a specific resident with a character accusation ("X is a
thief") or mob-justice language, and excludes it from clustering with a
retrievable, human-readable reason -- see `docs/ai-usage.md` for why this
exists as its own module.

### A deliberate stack deviation, disclosed

CLAUDE.md specifies FastAPI + Firestore + Gemini via Vertex AI on Cloud
Run. This iteration was built in a sandbox with **no package-registry
access** (pip/apt both blocked by network policy), so `app/` runs on the
Python 3.10 standard library only -- `http.server` instead of FastAPI,
SQLite instead of Firestore, a deterministic rule-based text processor
instead of a live Gemini call. Every interface is written to the shape the
real dependency would need (`app/llm.py`'s `LLMClient` protocol and
`VertexGeminiClient`; `app/storage.py`'s `Store` and the documented
`FirestoreStore`; `app/main_fastapi.py` as an untested-but-structurally-
ready FastAPI adapter over the same business logic). Full explanation in
`docs/ai-usage.md`. This is why `requirements.txt` lists packages that
`app/` itself does not currently import.

### Not yet built (see `CLAUDE.md`'s Day 2-5 plan and cut order)

Voice intake/transcription, a second locale beyond the Yoruba prompt stub,
real SMS-provider webhook signature verification, the actual Vertex/Gemini
wiring, and Cloud Run/Terraform deployment config.

## Running it

No install required for the demo or the tests -- everything below uses
only the Python 3.10 standard library plus Jinja2 and PyYAML, which ship
with this repo's target environment. If they're missing:
`pip install -r requirements.txt` (only the `jinja2`/`pyyaml` lines are
actually needed to run this iteration; the rest of that file is the
production stack listed above).

```bash
# run the desk + ingest server (http://127.0.0.1:8000)
python3 -m app.server

# in another terminal: submit a demo report
curl -s -X POST http://127.0.0.1:8000/simulate/inbound \
  -H 'Content-Type: application/json' \
  -d '{"id":"demo-1","to":"40404*REPORT-OKEADO2","from":"+2348011112222","text":"Someone was checking gates along Alade Street late last night."}'

# then open http://127.0.0.1:8000/desk?community=oke-ado-phase2
```

Run the test suite (35 tests, covers every item in CLAUDE.md's "Tests that
must pass" list):

```bash
python3 -m unittest discover -s tests -t . -v
```

Replay the seed dataset (60 reports across six weeks, two communities --
see `seed/generate_seed.py`'s module docstring for exactly what scenario
each report is there to demonstrate) through the real pipeline and print a
per-cluster summary:

```bash
python3 seed/replay.py
python3 seed/replay.py --file seed/bodija_scale_replay.json   # scale-slide illustration
python3 seed/replay.py --sensitivity                          # loose/suggested/strict thresholds, side by side
```

## Repo layout

```
CLAUDE.md              the brief this implements
app/
  config.py            loads config/*.yaml -- adding a community/language/pattern is a config change only
  models.py, storage.py    SQLite-backed Store (documented Firestore swap at the bottom of storage.py)
  hashing.py            sender phone -> salted hash, never stored in plaintext
  llm.py                LLMClient interface: RuleBasedClient (runs today) / VertexGeminiClient (production, documented)
  redaction.py           the identity-stripping layer
  targeting_guard.py     named-neighbour-accusation guard
  classifier.py          normal vs protected channel
  extraction.py          pattern scoring against config/patterns.yaml
  clustering.py          corroboration threshold + profiling-guard integration
  profiling_guard.py      >60%-redacted cascade check
  audit.py, referral.py   audit log entries, referral-brief generation
  pipeline.py, ingest.py  orchestration + durable, retryable webhook intake
  server.py              the desk UI + ingest HTTP server (stdlib http.server) -- what's actually tested
  main_fastapi.py        untested reference FastAPI adapter for Cloud Run deployment
  templates/             server-side Jinja2 templates for the desk UI
config/                 communities, thresholds, patterns, redaction terms, accusation terms -- all data, no code
prompts/                versioned LLM prompts (redaction, classification, extraction; en-NG + yo stub)
seed/                   generate_seed.py, reports.json, bodija_scale_replay.json, replay.py
tests/                  35 tests, one file per component, covering every CLAUDE.md-required test
docs/ai-usage.md         AI-usage log (what was delegated, what was rejected, a bug a test caught)
```

## Submission checklist status

- [x] GitHub repo, README explaining what it does and how to run it (this file) -- not yet pushed public
- [ ] Demo video
- [ ] Pitch deck (PDF)
- [ ] Written summary
