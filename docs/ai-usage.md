# AI usage log

This file is itself a CLAUDE.md-required artefact ("Record at least one case
where a test caught an agent-introduced bug... This file is itself an
artefact of the practice"). Updated at the end of each build session, per
CLAUDE.md's AI-coding-usage section. Newest session first.

---

## Session 1 -- 16 September 2026 (Day 1 of the plan)

**Delegated:** the entire first iteration, end to end, to Claude (Cowork/
Claude Code), working from this repo's `CLAUDE.md` as the brief and a
connected folder on the developer's machine as the target. In one session:
the config model, all six scoped components (ingest, redaction, channel
classifier, clustering with corroboration threshold, verification desk UI,
profiling guard), the audit trail, referral-brief generation, the seed
dataset and replay harness, and the test suite below. This runs ahead of
the five-day plan's Day 1 scope (which stopped at redaction) because a
single agent session could move faster than a human day; Day 2/3 items
(classifier, clustering, desk UI, profiling guard) were pulled forward
rather than left idle.

**Rejected / changed from the brief, and why:** CLAUDE.md specifies Python
+ FastAPI + Cloud Run + Firestore + Gemini via Vertex AI. The sandbox this
session ran in turned out to have no package-registry access at all --
`pip install fastapi` and `apt-get update` both failed with `403 Forbidden`
from the network policy, confirmed via the sandbox's own diagnostic
endpoint rather than assumed. Two options: write FastAPI/Firestore/Vertex
code that could not be run or tested in this environment, or build the
first iteration on the standard library only, fully tested, with the
production stack as a documented, structurally-ready swap. Chose the
second, and disclosed it rather than quietly shipping unverified code:

- `app/server.py` (the tested implementation) uses `http.server` instead
  of FastAPI; `app/main_fastapi.py` is a parallel, untested reference
  adapter over the *same* business-logic modules, marked as such in its
  own docstring, for when the project moves to a machine with network
  access.
- `app/storage.py` uses SQLite instead of Firestore, behind the same
  method surface a `FirestoreStore` would need to implement (documented
  at the bottom of that file, not yet written).
- `app/llm.py` defines an `LLMClient` interface with a deterministic
  `RuleBasedClient` (what actually runs today, config-driven off
  `config/redaction_terms.yaml`, `config/patterns.yaml`, etc.) and a
  `VertexGeminiClient` that reads the versioned `prompts/*.md` files and
  raises a clear, actionable error if constructed without
  `google-cloud-aiplatform` installed, rather than silently no-op-ing.

This means every test in this repo runs today, with no setup, on a bare
Python 3.10 standard library -- which was the more defensible trade for a
five-day solo hackathon than a stack nobody in this session could verify
works.

**Also added, beyond the six named components, and disclosed as such:**
`app/targeting_guard.py`, a named-target-accusation guard. CLAUDE.md's
required test list includes "a malicious report targeting a named
neighbour does not escalate, and the refusal reason is retrievable and
human-readable," and design rule #1 says intake asks what was observed,
never who -- but no single one of the six scoped components is specified
to own that check. Redaction (component 2) strips *stranger* identity
markers, which is a different failure mode from a report that names a
*known* resident and attaches a character accusation. Interpreted the gap
as needing a small, explicit guard rather than folding it awkwardly into
redaction or clustering, and named it in the scope as an addition, not a
silent expansion.

**Where the agent was wrong, and how it was caught:** running
`seed/replay.py` by eye during development (not just the automated tests)
surfaced a protected-channel report --
`"One of the Amotekun operatives has been extorting okada riders..."` --
showing as 100% redacted, which was not the intended seed scenario for
that report. Traced it to `app/llm.py`'s `RuleBasedClient.redact`: the
first implementation matched each redaction phrase with plain substring
search (`re.escape(phrase)`, no word boundaries), so the three-letter
ethnicity entry `"Tiv"` (from `config/redaction_terms.yaml`) matched
*inside* the ordinary words "opera**tiv**es" and "rela**tiv**es." Fixed by
anchoring every match to `\b...\b` word boundaries, and locked the fix in
with a regression test,
`tests/test_redaction.py::test_no_false_positive_on_ordinary_words_containing_a_term`,
so this class of bug cannot silently return. A second, smaller instance of
the same "seed text vs. config keyword phrasing" mismatch was caught the
same way (a seed report read "drums **were** being offloaded" while
`config/patterns.yaml`'s keyword is the exact phrase "drums being
offloaded", so the report scored 0 against every pattern and fell through
to `unclassified` instead of `explosives_storage`) -- fixed by editing the
seed text to match. Both are now called out explicitly in code comments
(`app/llm.py`) so a future reader does not reintroduce either.

**Verified, not just asserted:** all 35 tests in `tests/` pass on a plain
`python3 -m unittest discover -s tests -t . -v` (see README for the exact
command); `seed/replay.py` was run against both seed files and its
console output checked by hand against the scenario `seed/generate_seed.py`
documents it should produce (which distinct-sender counts, which cluster
statuses) before being treated as done.

**Not yet done** (see CLAUDE.md's cut order and Day 2-5 plan; nothing here
was silently dropped): voice intake and transcription; a second locale
beyond the Yoruba prompt stub (`prompts/redaction_v1_yo.md` exists and is
routed through the same pipeline, but has not been reviewed by a fluent
speaker, and is not itself deployment-ready); real Africa's Talking/Termii
webhook signature verification (`app/server.py`'s webhook route accepts
any POST -- fine for a demo, not for production, and named as a gap in
`.env.example`); actually wiring and calling `VertexGeminiClient`;
Terraform/IaC for the Cloud Run + Firestore deployment (CLAUDE.md's
variable-based-config rule is already followed in `config/*.yaml`, but no
IaC has been written yet, so there is nothing to check that rule against
yet); the threshold-sensitivity deck slide's numbers have the apparatus
(`seed/replay.py --sensitivity`) but have not themselves been run and
transcribed into the deck.

**Commit messages** in this repo's git history describe intent (what
changed and why) rather than just "update files," per CLAUDE.md's
AI-coding-usage note that the git history itself is evidence.
