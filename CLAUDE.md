# CLAUDE.md

Working name: **Àkíyèsí** (Yoruba, "observation / taking notice"). Rename if you prefer.

## What this is

A community early warning system. Residents send observations by SMS or voice from
any phone, including feature phones. An LLM pipeline strips identity content, then
clusters weak individual observations into corroborated patterns for the
neighbourhood's own security committee. A separate protected channel lets residents
report the security apparatus itself.

Andela x Open Society Foundations hackathon, "Information you can trust".
**Deadline: 21 September 2026, 23:59 UTC. Five days. Solo.**

Tracks: **Stability & Social Cohesion** (primary), **Safety, Reporting & Protection**
(secondary). Cross-track entries are welcomed.

## Framing (this governs every artefact, do not drift from it)

The judges are Open Society Foundations and Build Up. Peacebuilders. Their stated
thesis is shifting power to communities and away from security-led approaches. A tip
line that feeds a curfew, barrier gates and a hired security outfit can read as
strengthening informal policing, which is close to the opposite of what they fund.

So the framing is fixed:

- **Lead with protection from wrongful accusation, not with catching criminals.**
  The redaction layer's primary beneficiary is the innocent stranger.
- **The whistleblower channel is the credential, not a feature.** It lets residents
  report gatemen, hired security and community leadership. It is what makes this
  accountability infrastructure rather than an informant network. Give it real
  airtime in the video.
- **Say plainly: no enforcement power, no public accusations.** The system produces
  no public map, no public list, no public feed.
- **Name Ushahidi in the deck, before a judge does.** SMS incident reporting is a
  worn groove going back to 2008. The differences, stated explicitly: they publish
  to a public map, this deliberately refuses to publish; they collect reports, this
  aggregates signals too weak to report individually; they take text as given, this
  strips identity before analysis.

Vocabulary: community early warning, not crime reporting.

## Judging, and what it means

Four equally weighted axes, 25 percent each.

| Axis | What earns it here |
|---|---|
| **Uniqueness** | The redaction layer and the whistleblower channel. Nothing else does either. |
| **Scalability** | Community, language and pattern definitions are config, never code. |
| **AI Coding Usage** | A full quarter of the score. Documented continuously, never retrofitted. |
| **Presentation** | Explicit track alignment in the first minute of the video and deck. |

Impact and ethics are not scored categories. The guardrails still matter enormously,
but they earn points as **uniqueness**. Frame them that way everywhere.

## The real situation (the demo anchor)

A neighbourhood in Ibadan. Burglaries rising nearby, and a tip that the gang was
moving here next. The community erected barrier gates, imposed a curfew, hired
Amotekun (the Oyo State regional security outfit), and created a WhatsApp group to
collect tips and push information back out.

That system is live now. Three gaps, one feature each:

1. **Coverage.** It runs on WhatsApp. Roughly 55 to 60 percent of adults in the
   South West have no smartphone. The people closest to the raw information are
   exactly the ones excluded: night guards, okada riders, street traders, artisans,
   domestic staff. They see the street at 2am and they are not in the group.
   → **SMS and voice intake.**

2. **Anonymity.** No anonymity on a WhatsApp group, so an insider cannot report
   without fear of reprisal.
   → **Protected channel.**

3. **Aggregation.** No way to turn many one-off statements into a signal the
   committee can act on.
   → **Clustering with a corroboration threshold.**

## The core insight (do not lose this)

**This is not a reporting tool. It is an aggregation tool.**

One person noticing men unloading sacks into a house at night is nothing. They will
not post it, because alone it sounds like nothing and they would feel foolish. Forty
such observations across six weeks in a four-street radius is a pattern no single
human holds. The signal already exists at street level. There is no aggregator.

The LLM's job is not to judge reports. It is to make weak signals survive long
enough to cluster.

## Scope (deliberately small)

Six components. Nothing else.

1. Ingest: SMS webhook plus a simulated-inbound endpoint for demo reliability
2. Redaction layer
3. Channel classifier: normal or protected
4. Clustering with corroboration threshold
5. Verification desk UI with escalate action, audit log, referral brief
6. Profiling guard

Explicitly **not** building: recusal routing, landmark adjacency maps, incident fast
paths, time-decay weighting, WhatsApp API integration, reporter accounts, real
telephony provisioning, production auth, any public output.

The WhatsApp digest is a copyable text block, pasted by hand in the demo.

## Design rules

1. **Intake asks what was observed, never who.** Behaviour, time, location. The
   intake script is the first filter.

2. **Redaction before clustering.** Strip nationality, ethnicity, religion, tribe,
   and stranger or foreigner markers before the clustering model sees the text. A
   discrete module with its own test suite. This is the single most important
   component and the strongest uniqueness claim.

3. **Corroboration threshold. Never escalate on one report.**
   Normal channel: **3 distinct senders across at least 3 days surfaces a watch.
   5 escalates.** Both values in config.
   Protected channel: **threshold is 1.** A whistleblower is by definition alone.
   Goes straight to the protected recipient, labelled uncorroborated. Say this
   asymmetry out loud in the demo, it shows the problem was understood rather than
   one rule applied everywhere.

4. **Protected channel recipient is the landlord association.** Separate recipient
   list in config. The desk never sees protected content. Do not show timestamps
   finer than daily granularity in the desk view; in a neighbourhood of a few
   hundred, timing deanonymises.

5. **Profiling guard.** If more than 60 percent of a cluster's reports were redacted
   for identity content, flag it as a possible profiling cascade and require review
   before escalation. Roughly thirty lines of code, and a strong uniqueness point: a
   cluster made mostly of stripped reports is suspicion about a person, not
   observation of behaviour.

6. **Audit trail on every escalation.** Who decided, on what evidence, when.

7. **Anonymity by default.** No phone number stored in plaintext beside report
   content. Hash the sender for deduplication and rate limiting, nothing more.

8. **Freshness visible.** Every cluster carries a last-updated timestamp and an age.

Why this matters concretely: a curfew makes "stranger seen out after curfew" the
single most common report shape, and that is exactly the shape that becomes
profiling. With gates, a curfew and armed security already operating, a wrong
pattern sends Amotekun to a house.

## Government bridge (required by the brief)

The brief says the project must help people improve how they engage with governments
and public services. Amotekun is a state government outfit, so the referral pathway
is the government bridge and it must be **built and visible**.

Every escalation produces a structured referral brief: observation summary,
corroboration count, time window, location, redaction record. Cite this explicitly
in the deck against that line in the brief.

## Scalability seams

Three things are config, never code:

- **Community.** One inbound number or extension per community. Clustering scopes by
  construction, not by a geo field the reporter must supply. New community = one
  config row, and there is a test for that.
- **Language.** Intake and redaction prompts are locale-parameterised. Ship Yoruba
  and Nigerian English, plus a stub locale (French or Portuguese) that provably
  routes through the same pipeline. OSF works across Arabic, French, Portuguese and
  many local languages.
- **Pattern definition.** Data, not logic. Burglary casing is the demo. The same
  pipeline over a different pattern definition catches illegal explosives storage.

**Bodija goes on the scale slide, not in the demo.** Ibadan, 16 January 2024.
Illegal miners stored explosive devices in an occupied residential house. Two to
three killed, 77 injured, more than 20 buildings damaged. Neighbours had lived
beside that house for weeks. Same architecture, different pattern definition.

Be honest about the unit of deployment: this needs a functioning community committee
and a per-community number. Do not claim frictionless scale, state the cost.

## Stack

Optimise for demo reliability over elegance.

- Python, FastAPI, Cloud Run
- Firestore: reports, clusters, audit log, community config
- Gemini via Vertex AI. Every prompt in a versioned `prompts/` directory, never
  inline. Prompts as files is also evidence for the AI usage score.
- Africa's Talking or Termii for SMS
- Desk UI: server-side templates. No React.

If any infrastructure-as-code is written, use a variable-based approach throughout
(`var.project_id` and so on). No hardcoded values.

**Toll-free is a deployment question, not a demo question.** Real shortcodes go
through NCC and an aggregator, which is weeks. Use a normal provider number and
document the toll-free path in the deck with named steps and costs.

## AI coding usage: 25 percent of the score

A deliverable, generated while building, not reconstructed at the end.

- `docs/ai-usage.md` updated at the end of every session: what was delegated, what
  was rejected, where the agent was wrong and how it was caught.
- Commit messages describe intent. The git history is evidence.
- `prompts/` holds every model prompt as a versioned file.
- Record at least one case where a test caught an agent-introduced bug. That is the
  most credible evidence of disciplined AI-assisted development available, and it is
  a natural advantage for a QA lead.
- This file is itself an artefact of the practice. Reference it in the summary.

## Five-day plan

**Day 1 (16 Sep).** Repo, config model, ingest webhook plus simulated inbound,
report store. Redaction layer and its tests. Build redaction first, or it gets cut.

**Day 2 (17 Sep).** Channel classifier, extraction, clustering, threshold, seed
replay harness.

**Day 3 (18 Sep).** Desk UI, escalate action, audit log, referral brief, protected
channel delivery, profiling guard.

**Day 4 (19 Sep).** Voice intake with transcription. Stub second locale. Threshold
sensitivity run. Full end-to-end replay working.

**Day 5 (20 Sep).** Freeze code. Demo video, deck, README, written summary,
`docs/ai-usage.md` finalised.

**21 Sep.** Buffer and submit. Do not plan to build.

Cut order if time runs short: second locale, then voice intake, then profiling
guard. Never cut redaction, the threshold, or the protected channel.

## Seed data

60 to 100 reports across six weeks in `seed/` as replayable JSON.

Real material if obtainable: ten to fifteen anonymised tips from the existing
WhatsApp group with what happened next. No other entrant can produce that. Fill the
rest synthetically, mixing:

- weak signals that cluster into one real pattern
- ambient noise that must not cluster (noise complaints, lost goats, arguments)
- near misses that sit below threshold
- curfew-shaped profiling reports that must be redacted
- adversarial reports targeting a named neighbour
- protected-channel reports implicating a gateman or security member

## Tests that must pass

The QA discipline is the competitive edge and doubles as AI-usage evidence.

- A report naming nationality, tribe or religion is redacted before clustering, and
  the identity text never reaches the pattern store
- "Stranger seen after curfew" is reduced to observed behaviour only
- A malicious report targeting a named neighbour does not escalate, and the refusal
  reason is retrievable and human-readable
- Fifteen reports from one hashed sender do not meet the threshold
- Three reports in one hour do not meet the 3-day span requirement
- A protected-channel report is never visible to a desk user
- Desk view exposes no timestamp finer than daily
- Profiling guard fires on a cluster that is 60 percent redacted
- Bodija replay: seeded weak signals cross the threshold before the seeded incident
- A dropped webhook is retried, not silently lost
- A non-English report is handled or fails loudly, never silently discarded
- Adding a community requires a config row and no code change

## Threshold sensitivity (day 4, one deck slide)

The numbers cannot be validated against reality in five days, and a judge may ask.
Do not defend the values, show the apparatus. Run the seed replay at loose,
suggested and strict settings and report: true patterns surfaced, false clusters,
how early the signal appeared. That reframes the question from "are your numbers
right" to "here is the tuning method, per community."

## Submission checklist

- [ ] **GitHub repo**, public, README explaining what it does and how to run it
- [ ] **Demo video**, mp4/mov/webm/avi, under 250MB
- [ ] **Pitch deck**, PDF only, under 100MB: problem, users, solution, impact
- [ ] **Written summary**: the track, information sources, approach to trust and
      accuracy, how AI tools were used

The deck must address all seven operating constraints from the brief: trust and
verification, low bandwidth and limited access, accessibility and inclusion, privacy
and security, multilingual access, local relevance, clear next steps.

## Demo video must include

One scene of the system **refusing**: a malicious report crafted to target a
neighbour, and the pipeline declining to escalate it, with the reason on screen.

Almost no solo entrant will demonstrate their own system rejecting bad input. That
scene carries the uniqueness argument better than any feature.
