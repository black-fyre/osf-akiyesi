Written summary: Àkíyèsí

Andela x Open Society Foundations Hackathon, "Information You Can Trust." Submitted by Fehintoluwa Dahunsi, Nigeria, solo.

WHAT THIS IS

Àkíyèsí (Yoruba for "observation, taking notice") is a community early-warning system that runs over plain SMS, so it works on basic and feature phones, not just smartphones. A resident texts a toll-free number, or calls it to leave a voice message that gets transcribed, and describes whatever they actually saw, in their own words. We cannot control what a resident chooses to say, and with a curfew and armed security already active in the neighbourhood, people naturally reach for who someone looked like, a stranger, a nationality, a tribe, rather than only what that person did. That is exactly the danger: a report that is really about identity rather than behaviour is what turns a neighbourhood watch into wrongful suspicion of an innocent person, and a wrong pattern here can send an armed guard to someone's door. So before an AI model, or any human, ever analyses the text, it strips out any nationality, ethnicity, religion, or "stranger" language, and only the behaviour survives, so what moves forward is a description of an action, never a description of a person. The redacted observation is then scored against known behaviour patterns, currently burglary casing and, separately, illegal explosives storage, and held until independent people who do not know each other describe the same pattern: normally at least 3 distinct senders across at least 3 separate days before it becomes visible to anyone, 5 senders before it can actually be escalated. Only then does it reach the neighbourhood's own security committee, as a structured brief, never a raw message thread. A separate, anonymous channel lets a resident report the security apparatus itself, a gateman, a hired guard, a committee member, without fear of reprisal; that is the one case where a single report is enough to act on, and it is explicitly labelled uncorroborated rather than treated as verified.

The value: my own neighbourhood in Ibadan already runs its tip line on WhatsApp. That excludes the roughly 55 to 60 percent of adults in the urbanised South West who have no smartphone, who are also the people physically closest to the street at night: night guards, okada riders, traders. It has no anonymity, so nobody can report the guards themselves. And it has no way to turn forty separate, individually forgettable "someone was outside at 2am" messages into the one pattern they actually describe together. Àkíyèsí is built to close exactly those three gaps, on infrastructure a volunteer security committee could realistically run.

TRACK

Primary: Stability & Social Cohesion. The idea started as a stability problem, not an app idea. When I moved into the Orogun neighbourhood in Ibadan, there had been a rise in burglaries nearby and a tip that the gang behind them was coming here next. The neighbourhood put up barrier gates, started a curfew, hired Amotekun (the regional security outfit), and created the WhatsApp group described above to collect tips and push information back out. That response reduces everyday friction and prevents escalation exactly the way this track describes, but the WhatsApp group itself is what quietly locks out the people standing closest to the street.

Secondary: Safety, Reporting & Protection. The protected channel, letting residents report the security apparatus itself without fear of reprisal, is squarely this track's territory: anonymity, trust, and a clear pathway to action.

INFORMATION SOURCES

Every piece of information Àkíyèsí acts on comes directly from someone on the ground, in their own words, describing what they personally saw. Nothing is scraped, aggregated from social media, or passed along secondhand. There are two intake channels: the general toll-free line open to anyone, and the separate protected line for reporting the security apparatus, where reporters expect anonymity.

Because no single report is trusted on its own, the real source of any actionable signal is corroboration across people who do not know each other, not any one account, and the specific thresholds are config values a community can retune, not hardcoded.

The pattern definitions themselves come from real local context rather than being guessed at. The burglary-casing pattern used in the demo reflects what actually happened in Orogun. A second pattern, illegal explosives storage, reflects the Bodija, Ibadan explosion of 16 January 2024, when illegal miners who had stored explosives inside an occupied residential house for weeks were confirmed by Governor Seyi Makinde's office to have caused 2 deaths and 77 injuries; it is shown on the scale slide as proof the same pipeline generalises to a different threat, not treated as the main demo. Patterns live in config, not code, so a community can define a new one from its own experience without a rebuild, and can even give a specific pattern, like a weapon or armed-robbery sighting, its own faster bar (2 senders within a day instead of 5 within 3) while a single such report still only ever surfaces as a priority item for the committee to look at, never an automatic action.

APPROACH TO TRUST AND ACCURACY

Trust and accuracy are enforced structurally, not left to a reviewer's judgement:

No single report can trigger anything. Nothing reaches a human decision-maker on the strength of one account, other than the protected channel, which is labelled as such.

Identity content is stripped before an AI ever analyses a report. Nationality, ethnicity, religion, and "stranger" markers are removed before anything downstream sees the text, so the loudest, most bias-prone signal in a neighbourhood watch, a report that is really about who someone is rather than what they did, never reaches the pattern-matching stage.

A profiling guard flags any cluster where more than 60 percent of its underlying reports needed identity redaction and holds it for manual review, since that shape is closer to suspicion about a person than a verified behavioural pattern.

A named-target guard rejects a report that accuses a specific resident by name rather than describing behaviour, and the refusal reason is retrievable and human-readable, because an unverified accusation reaching a security committee is the single biggest trust failure a system like this could cause.

Every escalation carries a structured audit trail: who decided, on what evidence, when. Nothing is escalated anonymously on the institutional side, even though reporters stay anonymous on theirs.

USE OF AI TOOLS

The core idea, the Orogun story, the specific gap in the WhatsApp group, the toll-free SMS approach, and the subnetwork-per-community scaling model all originated with me, before any AI assistance, in line with the hackathon's rule that the core capstone idea must not be AI-generated.

From that brief, I used Claude (Anthropic's Claude Code, via Cowork) to build the proof of concept: the SMS ingest pipeline, the identity-redaction layer, the channel classifier, the corroboration clustering, the verification desk UI, the profiling guard, and an 80-test automated suite covering specific failure modes, including a malicious report that should not escalate, a cluster that is mostly redacted content, and a dropped webhook that must be retried. The redaction and pattern-matching layer is itself designed to run on Claude via the Anthropic API in production; what this proof of concept actually runs on, and what the 80 tests exercise, is a deterministic rule-based version of the same logic, so it can be graded without a live API key.

A full, session-by-session log of what was delegated, what was rejected, and where the agent was wrong and how it was caught, including a real bug where an early redaction match false-triggered inside unrelated words like "operatives," caught by eyeballing test output and locked in with a regression test, is in docs/ai-usage.md in the repository, updated continuously during the build rather than written after the fact.
