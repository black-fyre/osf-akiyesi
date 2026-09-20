Written summary — Àkíyèsí

Andela x Open Society Foundations Hackathon, "Information You Can Trust." Submitted by Fehintoluwa Dahunsi, Nigeria, solo.

TRACK

Primary: Stability & Social Cohesion. The problem started as a stability problem, not an app idea. When I moved into the Orogun neighbourhood in Ibadan, there had been a rise in burglaries nearby and a tip that the gang behind them was coming here next. The neighbourhood put up barrier gates, started a curfew, hired Amotekun (the regional security outfit), and created a WhatsApp group to collect tips and push information back out. That response reduces everyday friction and prevents escalation exactly the way this track describes, but the WhatsApp group itself quietly locks out the people standing closest to the street: night guards, okada riders, traders, anyone without a smartphone.

Secondary: Safety, Reporting & Protection. The system also has to let residents report the security apparatus itself (a gateman, a hired guard, a committee member) without fear of reprisal, which is squarely this track's territory: anonymity, trust, and a clear pathway to action.

INFORMATION SOURCES

Every piece of information Àkíyèsí acts on comes directly from someone on the ground, in their own words, describing what they personally saw: behaviour, time, roughly where. Nothing is scraped, aggregated from social media, or passed along secondhand. There are two intake channels: a general toll-free line open to anyone, and a separate protected line for reporting the security apparatus itself, where reporters expect anonymity.

Because no single report is trusted on its own, the real source of any actionable signal isn't any one person, it's corroboration across people who don't know each other. A pattern only reaches the community's security committee once at least 3 distinct senders describe the same behaviour across at least 3 separate days (5 senders to escalate; both numbers are config, not hardcoded). The one deliberate exception is the protected channel: a single report there is enough to route to the landlord association, but it's explicitly labelled "uncorroborated" rather than treated as verified, because a whistleblower is by definition alone.

The pattern definitions themselves come from real local context rather than being guessed at. The burglary-casing pattern used in the demo reflects what actually happened in Orogun. The explosives-storage pattern shown on the scale slide reflects the Bodija, Ibadan explosion of 16 January 2024, when illegal miners who had been storing explosives inside an occupied residential house for weeks were confirmed by Governor Seyi Makinde's office to have caused 2 deaths and 77 injuries. Patterns live in config, not code, so a community can define one from its own experience without a rebuild.

APPROACH TO TRUST AND ACCURACY

Trust and accuracy are enforced structurally, not left to a reviewer's judgement:

No single report can trigger anything. See the corroboration threshold above; nothing reaches a human decision-maker on the strength of one account, other than the protected channel, which is labelled as such.

Identity content is stripped before an AI ever analyses a report. Nationality, ethnicity, religion, and "stranger" markers are removed before anything downstream sees the text, so the loudest, most bias-prone signal in a neighbourhood watch, a report that's really about who someone is rather than what they did, never reaches the pattern-matching stage.

A profiling guard flags any cluster where more than 60 percent of its underlying reports needed identity redaction and holds it for manual review, since that shape is closer to suspicion about a person than a verified behavioural pattern.

A named-target guard rejects a report that accuses a specific resident by name rather than describing behaviour, and the refusal reason is retrievable and human-readable, because an unverified accusation reaching a security committee is the single biggest trust failure a system like this could cause.

Every escalation carries a structured audit trail: who decided, on what evidence, when. Nothing is escalated anonymously on the institutional side, even though reporters stay anonymous on theirs.

USE OF AI TOOLS

The core idea, the Orogun story, the specific gap in the WhatsApp group, the toll-free SMS approach, the "like Flock cameras, but human intelligence, government-free" framing, and the subnetwork-per-community scaling model all originated with me, before any AI assistance, in line with the hackathon's rule that the core capstone idea must not be AI-generated.

From that brief, I used Claude (Anthropic's Claude Code, via Cowork) to build the proof of concept: the SMS ingest pipeline, the identity-redaction layer, the channel classifier, the corroboration clustering, the verification desk UI, the profiling guard, the audit trail, and a 35-test automated suite covering specific failure modes, including a malicious report that shouldn't escalate, a cluster that's mostly redacted content, and a dropped webhook that must be retried.

A full, session-by-session log of what was delegated, what was rejected, and where the agent was wrong and how it was caught, including a real bug where an early redaction match false-triggered inside unrelated words like "operatives," caught by eyeballing test output and locked in with a regression test, is in docs/ai-usage.md in the repository, updated continuously during the build rather than written after the fact.
