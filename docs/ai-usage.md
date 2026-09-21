# AI usage log

This file is itself a CLAUDE.md-required artefact ("Record at least one case
where a test caught an agent-introduced bug... This file is itself an
artefact of the practice"). Updated at the end of each build session, per
CLAUDE.md's AI-coding-usage section. Newest session first.

---

## Session 7 -- 21 September 2026 (submission day, later)

**Delegated:** two requests from the author, in this order. First, a simpler
sister to the demo console, "supporting a narrative rather than enforcing
one": ready-made messages for every scenario, one click each, with
presenter hints, landing in the app itself. Second, mid-build, "let's build
support for Yoruba as well."

**Presenter remote (`/demo/remote`, `app/templates/demo_remote.html`).** A
list of the scripted scenes as one-click messages, a "send next in story"
button (key `N`), a free-text composer, talking points per scene, and a
crib sheet whose numbers are read from config (`demo.presenter_numbers`),
so the crib cannot disagree with the rules. It sends through the console's
own `/demo/send`, so it adds no rules. Each send is announced on a
`BroadcastChannel`: the console draws the message's trace as if it had been
typed on its phone, and the desk, audit and inbox pages reload. Three Q&A
extras (one loud voice, a burst in one evening, everyday noise) carry a
declared outcome and are replayed by `tests/test_demo_console.py`, the same
way the scenes are, so a talking point such as "fifteen texts from one
phone are one person" cannot quietly stop being true.

**Yoruba.** Before this session the `yo` locale was accepted as a payload
hint and nothing else: redaction, pattern matching and the accusation guard
all used the community's English lists, so a Yoruba SMS was filed as
noise. Now:

- `app/locale_detect.py` detects each message's language from
  `config/locales.yaml` (Yoruba under-dot letters, or two distinct common
  Yoruba words), after an explicit hint and before the community default.
- `app/textnorm.py` makes every rule-based match ignore tone marks, so
  "Àjèjì" and "Ajeji" are the same word, and replaces the matched span in
  the original text, leaving the rest of the sender's spelling untouched.
- Yoruba lists in `redaction_terms.yaml`, `patterns.yaml` (all three
  patterns), `accusation_terms.yaml` (epithets, mob language, and the
  "Ole ni Bello" word order via `inverted_copulas`), and the classifier's
  protected-channel indicators.
- A demo scene, "Same rules, in Yorùbá", and a Yorùbá accusation Q&A extra.

**Where the agent was wrong, and how it was caught.** The first version
matched each message against the detected language plus the community's.
A throwaway replay of eleven hand-written messages, run before any tests
were written for the feature, showed two failures in the safety layers:

1. "Ajeji kan was loitering by the gate at night." was detected as English
   (too few Yoruba words), so the Yoruba stranger word "Ajeji" was **not
   redacted** and would have reached the pattern store.
2. "Baba Bello je ole, e lu u." (a named accusation plus a call to beat
   him) was too short to be detected as Yoruba, so the Yoruba accusation
   list never ran and the message was **stored**, not refused.

The fix was a design change, not a word-list tweak: the safety layers
(redaction, accusation guard, protected-channel fallback) now check every
language's lists on every message (`AppConfig.all_locales`), whatever was
detected. A wrong guess can only over-redact, which is the safe direction.
Detection now only steers pattern matching. Both messages are pinned in
`tests/test_yoruba.py`. A third near-miss was designed out before it
shipped: "ni" also means "at", so "awon ole ni Adeoye street" (robbers at
Adeoye street) would have matched a loose "<epithet> ni <Name>" rule. The
inverted form now requires the epithet to open the clause, and a test
proves the observation is stored, not refused.

**Rejected:** changing pattern scoring from substring to whole-word
matching at the same time. It would have been more correct for new Yoruba
keywords, but it changes English scoring the suite depends on ("gun" in
"gunshots"). Instead the one risky Yoruba keyword ("ada", cutlass, which
also sits inside other words) became the phrases "gbe ada" and "mu ada".

**Honest limits.** Every Yoruba list here was written for this build and
has not been reviewed by a fluent speaker from the community. That review
is a deployment step, and `config/locales.yaml` says so. The Claude backend
needs no Yoruba prompt to read Yoruba; it is given the merged keyword lists
for pattern scoring.

**Verified:** 135 tests pass (`python3 -m unittest discover -s tests -t .`),
including 18 new Yoruba tests and 6 new tests for the remote. The remote and the
live hand-off were driven in a headless browser: the story sent by keyboard
from the remote, the console drew each message's trace (including "Read as
Yorùbá"), and an open desk page reloaded to the new sender count, with no
page errors and no horizontal scroll at phone width.

---

## Session 6 -- 21 September 2026 (submission day)

**Delegated:** a browser front end for pushing demo messages through the
pipeline, on request ("a manual post endpoint doesn't seem very demo
friendly"), and a scripted demo built on it. The demo plan and the choice of
what to show were discussed with the author; the scenes below are the result.

**What was built:** `app/demo.py` and `app/templates/demo.html`, served at
`/demo`: a phone-shaped composer, a step-by-step trace of what the pipeline did
to each message, the committee's signal board, and a side drawer that opens
the real desk pages. Seven scenes are declared as data in `app/demo.py`, each
with the outcome it is supposed to produce.

**Decisions worth reviewing:**
- The console adds no rules. Messages go through `ingest.receive_webhook`, and
  the bars on the board come from a new `clustering.resolve_thresholds`, which
  `compute_clusters` now also uses. That is a pure extraction with identical
  behaviour, and the existing tests were left unchanged and still pass.
- Protected-channel text is never returned by `/demo/state` or `/demo/send`,
  including for a message that was rerouted to the protected channel by the
  content classifier. A test asserts it against the HTTP responses.
- Reset wipes every table, so the routes exist only in demo mode
  (`AppContext(demo_mode=True)`, set by `python3 -m app.server`; off by default
  for anything else, and `AKIYESI_DEMO_MODE=0` turns it off there too). A test
  asserts every `/demo` route is 404 with it off and that no data is touched.
- Messages can be backdated through the payload's existing optional `date`, so
  a three-day window fits into a few minutes. The page says so on screen.

**Verified:** 26 new tests in `tests/test_demo_console.py`, including one that
replays every scene through the real pipeline and checks its declared outcome,
and one that walks scene 1 sender by sender through
below-threshold, watch and ready. The full suite is 111 tests and passes on
Python 3.10 (the author's machine) and 3.11. The server was also started on
the author's machine and the console's endpoints exercised with curl.

**What running it in a browser caught, and the unit tests did not:** a
headless Chromium walk-through of all seven scenes, the drawer, escalation from
the drawer, reset and Auto mode found four problems, all fixed. The profiling
guard banner showed on a one-report cluster that had not met its threshold yet
(100% of one report), which read as a false alarm. Esc did not close the drawer
once focus was inside the desk page in it. Progress read "4 of 3 days" and "1
days". The first version of the layout pushed the phone and the board below the
fold once a scene caption appeared.

**Not done:** the page's JavaScript has no automated tests. The browser
walk-throughs were run by hand with throwaway scripts that are not in the repo.
The scene messages are synthetic and were written to match the keyword lists
in `config/patterns.yaml`, so they show the pipeline working, not how well
keyword matching generalises to real messages.

---

## Session 5 -- 20 September 2026 (Day 5 of the plan)

**Delegated:** fixing a privacy gap in the durable inbound log, on request
("fix the code"), after it surfaced while fact-checking the rewritten
written summary against the code.

**How it was found, and where the agent was wrong:** the summary said
reports are stored as redacted text with a hashed sender and no phone
number. Before leaving that sentence in, the claim was checked against the
code path instead of against the README, and it did not hold.
`app/ingest.py` (Session 1) logs every raw webhook payload to `inbound_log`
so a dropped message can be retried, and nothing ever removed it: the
sender's phone number and the original, unredacted message text stayed in
the database permanently. That contradicted the README ("only the redacted
text is ever persisted"), the deck ("phone numbers are hashed, never stored
in plain text"), design rule #7, and a comment in
`tests/test_redaction.py` ("the raw text is never written to storage").
Session 1 wrote both the logging and the claims, and no test connected
them: the "identity text never reaches the pattern store" test only looked
at the `reports` table, and the raw text was in a different table. The
first draft of the summary sentence in this session ("never stored beside
report text") was also wrong until it was checked. It was caught by
reading the code, not by a test.

**What was changed:** `app/ingest.py` now replaces the phone number with its
salted hash before a payload is logged or processed, so the number is never
written to storage. `app/storage.py`'s `mark_inbound_status` replaces the
payload with a stub in the same UPDATE that marks a row `processed`, so the
original text is kept only while a message is waiting to be retried.
`app/pipeline.py`'s `parse_payload` accepts the hashed form (retried
payloads arrive already hashed) and its missing-field error no longer echoes
the whole payload, which had been copied into `inbound_log.error`. This is
small on purpose: field names and schema are unchanged, so no migration is
needed and the retry behaviour is untouched.

**Verified, not just asserted:** `tests/test_inbound_log_privacy.py` adds 5
tests. Run against the previous code (`git archive HEAD` into a scratch
directory), 4 of the 5 fail, and a direct check confirmed the old code left
both the number and the original text in the database, so the tests are
testing the real gap. On the fixed code the full suite is 85 tests (up from
80) and passes. The real server was also run end to end against a scratch
database: one report through `/simulate/inbound` and one message to an
unknown number through `/webhook/sms`, then the SQLite file inspected
directly. The processed row's payload was scrubbed, the unprocessed row kept
its text but held only the sender hash, no phone number appeared anywhere
in the file, and the desk still rendered.

**Not yet done:** a message that can never be processed (for example one sent
to an unconfigured number) stays in the retry log with its original text,
though no phone number, until it is processed; a production build would
need a retention limit on failed rows. The LLM response-parsing errors in
`app/llm.py` echo the model's JSON, which could carry message text into a
failed row's `error` column; not changed here. A local `data/akiyesi.db`
created before this fix (gitignored) may still hold old raw rows.

---

## Session 4 -- 20 September 2026 (Day 5 of the plan)

**Delegated:** a new escalation pathway for "high-signal" reports (the
developer's own example: a report mentioning a weapon or armed robbers),
on request ("I am thinking about adding a pathway certain high signal
words in a report get an accelerated escalation pathway"). Before writing
any code, laid out three options and their trade-offs, given the deadline
is the next day: (1) give a high-signal pattern its own lower
corroboration threshold plus a priority flag on a single report, never
bypassing the human/corroboration gate; (2) document it as a deferred
next step rather than touch tested core logic this close to the deadline;
(3) a true single-report bypass for matching keywords. Flagged (3)
explicitly as the option most likely to draw a pointed judge question,
since it would contradict a claim already in the written summary ("no
single report can trigger anything") and reopen the exact false-alarm/
profiling risk the redaction and corroboration layers exist to prevent --
especially given OSF/Build Up's stated thesis of shifting power away from
security-led responses. The developer chose (1).

**What was built:** a new `weapon_sighting` pattern in
`config/patterns.yaml`, marked `high_signal: true` with its own
`watch`/`escalate` thresholds (1 sender/0 days to watch, 2 senders/1 day
to escalate, against the community default of 3/3 and 5/3). `app/config.py`'s
`PatternDefinition` gained `high_signal`, `watch_override` and
`escalate_override` fields. `app/clustering.py`'s `compute_clusters()`
gained an optional `patterns` parameter: when supplied, a pattern's own
override is used if present, otherwise the community default -- omitting
the parameter (every call site and every test written before this
session) reproduces the exact old behaviour, so this is additive, not a
breaking change to an already-tested function. The seven real call sites
(`app/server.py` x3, `app/main_fastapi.py` x3, `seed/replay.py` x1) were
updated to pass `patterns=config.patterns` so the running app actually
uses it. The desk templates get a black "priority" badge next to a
high-signal pattern's name, in both the cluster list and the cluster
detail view, so a committee member can see at a glance which patterns
carry a lower bar and why (the badge's title attribute points at
`config/patterns.yaml`).

**Design rule #3 ("never escalate on one report") was checked, not just
asserted:** `tests/test_clustering.py` gained a
`HighSignalPatternThresholdTests` class (7 tests) that explicitly proves
a single `weapon_sighting` report only ever reaches `STATUS_WATCH`, that
two senders one day apart escalates but two senders in the same minute
does not (the override's own span floor is still enforced), that a
normal pattern's behaviour is unchanged when `patterns=` is passed, that
omitting `patterns=` falls back to the old uniform behaviour even for
`weapon_sighting`, and -- the test most worth having -- that the
profiling guard still blocks an escalation on this pathway exactly like
any other, so "accelerated" never means "unguarded."

**Where the agent caught its own near-miss before it shipped:** while
choosing keywords for `weapon_sighting`, checked
`RuleBasedClient.score_patterns` (`app/llm.py`) and found it does a plain
substring check with no word-boundary matching -- unlike `redact()`,
which was fixed for exactly this class of bug in Session 1 (the "Tiv"
inside "operatives" false-positive). A keyword list using "armed men" or
"armed robbers" would have made "two **unarmed** men were seen" score as
a weapon sighting, since "armed men" is a literal substring of "unarmed
men." Avoided the collision by choosing keywords that don't have this
containment problem ("gun", "weapon", "robbers", "machete", etc.) rather
than "armed X" phrases, and locked the choice in with a regression test
(`tests/test_extraction.py::test_unarmed_does_not_false_positive_on_armed_keyword`)
instead of only noticing it informally. `RuleBasedClient.score_patterns`'s
underlying substring-matching behaviour was left unchanged -- fixing it
properly (word-boundary matching like `redact()` already has) is flagged
below as a not-yet-done item, since it's a real, pre-existing gap this
session found but a wider change to make one day before the deadline than
this feature needed.

**Verified, not just asserted:** full suite -- 80 tests, up from 69 (7
new clustering tests, 5 new `tests/test_extraction.py` tests, the latter
a new file since none existed for `app/extraction.py` before) -- passes
on a plain `python3 -m unittest discover -s tests -t . -v`. Also ran the
real server end to end (`python3 -m app.server` against a scratch
database, submitted a report reading "Two men were seen carrying a gun
near the fence around 9pm." through `/simulate/inbound`, then fetched
`/desk?community=oke-ado-phase2`) and confirmed by eye that the rendered
HTML shows the report as a single-sender `watch` cluster carrying the new
priority badge -- not just that the Python-level test suite passes, but
that the feature actually renders correctly through the real HTTP path.

**Not yet done:** `RuleBasedClient.score_patterns`'s plain-substring
keyword matching (noted above) is a pre-existing gap, not introduced this
session, but this session is what surfaced it concretely; a proper fix
(word-boundary matching, matching `redact()`) is a good candidate for a
next session if time allows, but was deliberately not done here to keep
this change scoped to what the new pattern needed. The deck and written
summary were not updated to mention `weapon_sighting` -- the developer
had already signed off on both ("this is good to go") before this
session, so a mention was left for her to add herself if she wants the
demo script to include it, rather than re-editing a finalised deliverable
unasked.

---

## Session 3 -- 20 September 2026 (Day 5 of the plan)

**Delegated:** replacing Session 2's Gemini/Vertex AI wiring with a real
Claude/Anthropic API implementation, on correction ("i actually meant
claude" -- Session 2's "let's go with gemini" had been a misstatement).
Asked the developer two scoping questions before touching any file: (1)
add Claude as a new backend alongside the existing Gemini one, or replace
Gemini entirely; (2) whether CLAUDE.md, the deck and the written summary
(which all named "Gemini via Vertex AI" as the intended production stack)
should be updated too. She chose full replacement plus updating every
doc that named the old stack.

**What was actually replaced:** `app/llm.py`'s `VertexGeminiClient` class
is gone; `AnthropicClient` takes its place, calling the Anthropic Messages
API (`client.messages.create(model=, system=, messages=[...])`) instead of
Vertex AI's `generate_content`. The three pure response-validation
functions (`parse_redaction_response`, `parse_classification_response`,
`parse_extraction_response`) were kept completely unchanged and simply
reused -- their contract comes from `prompts/*.md`'s own "Output contract"
sections, not from any provider's SDK, so nothing about them was
Gemini-specific to begin with. `tests/test_llm_gemini_parsing.py` was
renamed to `tests/test_llm_response_parsing.py` to reflect that it was
never really Gemini-specific either. `tests/test_llm_gemini_client_wiring.py`
was replaced by `tests/test_llm_anthropic_client_wiring.py` (9 tests, one
fewer than the Gemini version's 10 -- Vertex AI's SDK builds one
`GenerativeModel` object per prompt, which the Gemini wiring tests checked
for; the Anthropic SDK takes a system prompt per call instead, so that
particular test no longer applies, not because coverage was dropped).
`scripts/smoke_test_gemini.py` became `scripts/smoke_test_claude.py`, same
role. `requirements.txt` swaps `google-cloud-aiplatform` for `anthropic`.
`.env.example`, `README.md`'s setup section, `CLAUDE.md`'s Stack line,
`config/redaction_terms.yaml`'s comment, and each `prompts/*.md` file's
"Used by" header were all updated to name `AnthropicClient`/Claude instead
of `VertexGeminiClient`/Gemini. Checked the deck and written summary
directly (`grep -i "gemini\|vertex"` against both) before editing them:
neither ever named Gemini or Vertex AI specifically -- both only ever said
"an LLM" -- so there was nothing to change in either.

**A genuine improvement this correction produced, not just a rename:**
confirmed by direct request that `api.anthropic.com` is actually reachable
from this sandbox -- a request to `/v1/messages` with no credentials
returns `401` (a real, responsive endpoint), not the `403` (fully blocked)
that `generativelanguage.googleapis.com` and `aiplatform.googleapis.com`
returned in Session 2. The `anthropic` Python package still can't be
`pip install`-ed here (no route to pypi.org, same package-registry
restriction documented since Session 1), so the live SDK call still can't
be exercised from this sandbox and `scripts/smoke_test_claude.py` still
exists for the developer to run herself -- but this is a narrower,
more honest gap than Session 2's: the network path to the provider itself
is proven open, and only the local package installation and a real API
key are missing, not connectivity to Anthropic at all.

**Where the agent was wrong, and how it was caught:** Session 2 built a
complete, tested, committed Gemini implementation on the strength of
"let's go with gemini" without re-confirming that phrase against what the
developer actually meant. She caught it herself, in the very next message
("i actually meant claude"), not through any test or review step on this
side. Recorded here plainly rather than folded quietly into a rename,
because a full backend swap one day before the deadline is exactly the
kind of AI-assisted misstep this log exists to surface, and because the
fix was cheap only because the pure parsing layer had been kept
provider-agnostic in Session 2 -- a design choice that turned out to pay
for itself here.

**Left unchanged, deliberately:** `AKIYESI_LLM_BACKEND` still defaults to
`rule_based`. The full suite -- 69 tests (Session 2's 70, minus one: see
the wiring-test-count note above) -- passes on a plain `python3 -m
unittest discover -s tests -t . -v`.

**Not yet done:** the live Anthropic API call itself, pending the
developer's own smoke test on a machine where the SDK can be installed.
Everything else already listed as not-yet-done in Session 1 is unchanged
by this session.

---

## Session 2 -- 20 September 2026 (Day 5 of the plan)

*Superseded by Session 3 above: the developer corrected the provider
choice from Gemini to Claude the same day, and `VertexGeminiClient` was
replaced by `AnthropicClient`. Kept below unedited as an accurate record
of what actually happened, not as a description of the current codebase.*

**Delegated:** wiring `app/llm.py`'s `VertexGeminiClient` into a real Vertex
AI implementation, on request ("let's start working on building in the
actual AI calls"), after confirming with the developer that Gemini should
stay the model provider (asked directly why Gemini was chosen in the first
place; answered honestly that it was her own choice in the original brief,
not something introduced later; she then said "let's go with Gemini").

**Constraint discovered before writing any code, not assumed:** confirmed
by direct request from both this build sandbox and the developer's own
device sandbox that `generativelanguage.googleapis.com`,
`aiplatform.googleapis.com` and `api.openai.com` all return `403`
(proxy-blocked); only `api.anthropic.com` is reachable. Surfaced this to
the developer via a structured question before writing anything, given
the one-day-to-deadline risk of adding a live external dependency to an
already-tested, already-disclosed submission, rather than either silently
attempting a workaround or silently declining the request. She chose to
proceed with Gemini anyway, understanding that the network call itself
could not be exercised from either sandbox this session has access to.

**What was actually built, given that constraint:** `VertexGeminiClient`
is now a real implementation, not a stub. It loads each of `prompts/*.md`
as a `GenerativeModel`'s `system_instruction`, calls `generate_content`
with `response_mime_type="application/json"` at `temperature=0`, and
validates the JSON that comes back. The response-validation logic was
deliberately split into three pure functions --
`parse_redaction_response`, `parse_classification_response`,
`parse_extraction_response` -- that take a plain dict and touch no
network, specifically so this half of the work could be genuinely
unit-tested despite the SDK being unreachable.
`tests/test_llm_gemini_parsing.py` (25 tests) exercises those functions
against response shapes copied from each prompt file's own worked
example, plus deliberately malformed variants: a missing key, a wrong
type, an unknown redaction category, a negative score, a `bool`
masquerading as an `int`. `tests/test_llm_gemini_client_wiring.py` (10
tests) goes one step further: it substitutes a fake
`vertexai`/`vertexai.generative_models` module via `sys.modules` and
proves `VertexGeminiClient` calls the real SDK's documented interface
correctly (`vertexai.init(project=, location=)`, one `GenerativeModel`
per prompt with the right `system_instruction`, the right
`generation_config`), and that a canned JSON reply round-trips correctly
through all three public methods, including error paths (empty response,
malformed JSON, a markdown-fenced ` ```json ` reply, a raised SDK
exception).

**What was not, and could not be, verified here:** an actual call to the
real Vertex AI API. `scripts/smoke_test_gemini.py` is a new script, meant
to be run by the developer herself on a machine with real GCP credentials
and network access, that makes three real calls (one per prompt) using
each prompt file's own worked-example input and prints the result next to
the expected output for her to check by eye. This is disclosed plainly in
`app/llm.py`'s module docstring, in `README.md`'s new "Real Gemini /
Vertex AI setup" section, and here, rather than presented as verified when
it is not.

**Left unchanged, deliberately:** `AKIYESI_LLM_BACKEND` still defaults to
`rule_based`. Nothing about the demo, the original 60 tests, or the
deterministic client changed in this session -- `vertex_gemini` is
strictly additive and opt-in, one day before the submission deadline, so
the tested path stays the tested path whether or not the developer runs
the smoke test before submitting.

**Verified, not just asserted:** the full suite -- 70 tests, the original
60 plus 35 new -- passes on a plain `python3 -m unittest discover -s tests
-t . -v`; `scripts/smoke_test_gemini.py` was run in this sandbox both with
`AKIYESI_GCP_PROJECT` unset and with the SDK absent, confirming both fail
with the intended clear, actionable message rather than an unhandled
traceback (it cannot be run to completion here, for the reason above).

**Not yet done:** the live Vertex AI call itself, pending the developer's
own smoke test on a machine with network access. Everything else already
listed as not-yet-done in Session 1 is unchanged by this session.

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
`.env.example`); `VertexGeminiClient` was wired to real Vertex AI calls in
Session 2 below, but the live network call has not itself been verified
from either sandbox this project was built in -- see that entry;
Terraform/IaC for the Cloud Run + Firestore deployment (CLAUDE.md's
variable-based-config rule is already followed in `config/*.yaml`, but no
IaC has been written yet, so there is nothing to check that rule against
yet); the threshold-sensitivity deck slide's numbers have the apparatus
(`seed/replay.py --sensitivity`) but have not themselves been run and
transcribed into the deck.

**Commit messages** in this repo's git history describe intent (what
changed and why) rather than just "update files," per CLAUDE.md's
AI-coding-usage note that the git history itself is evidence.
