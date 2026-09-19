# Written summary — Àkíyèsí

Andela × Open Society Foundations Hackathon, "Information You Can Trust." Submitted by Fehintoluwa, Ibadan, Nigeria, solo.

## Track selection

**Primary: Stability & Social Cohesion.** The problem started as a stability problem, not an app idea. When I moved into the Orogun neighbourhood in Ibadan, there had been a rise in burglaries nearby and a tip that the gang behind them was coming here next. The neighbourhood put up barrier gates, started a curfew, hired Amotekun (the regional security outfit), and created a WhatsApp group to collect tips and push information back out. That response reduces everyday friction and prevents escalation exactly the way this track describes, but the WhatsApp group itself quietly locks out the people standing closest to the street: night guards, okada riders, traders, anyone without a smartphone.

**Secondary: Safety, Reporting & Protection.** The system also has to let residents report the security apparatus itself (a gateman, a hired guard, a committee member) without fear of reprisal, which is squarely this track's territory: anonymity, trust, and a clear pathway to action.

## Information sources

- **Firsthand.** The Orogun neighbourhood response (gates, curfew, Amotekun, the WhatsApp group and its coverage gap) is my own lived account, not secondhand.
- **The Bodija, Ibadan explosion**, cited in the deck as the impact case: 16 January 2024, illegal miners had been storing explosives inside an occupied residential house; when it went off, Governor Seyi Makinde's office confirmed 2 killed and 77 injured, with more than 20 buildings damaged. Reported by [TheCable](https://www.thecable.ng/seyi-makinde-two-dead-77-injured-in-ibadan-explosion-caused-by-illegal-miners/), [Vanguard](https://www.vanguardngr.com/2024/01/illegal-miners-explosives-caused-ibadan-blast-makinde/), and [Sahara Reporters](https://saharareporters.com/2024/01/17/ibadan-explosion-illegal-miners-who-stored-explosives-home-are-malians-residents-claim), among others.
- **Smartphone access in Nigeria.** Early framing of this idea used an estimate that 55-60% of adults in the Southwest lack smartphone access; that number was my own informed estimate from watching who was actually reachable on the WhatsApp group, not a cited study. Checking it for this submission, I could not find a Southwest-specific published figure to confirm it against. What I did find: Pew Research (2017) measured smartphone ownership among Nigerian mobile users at 32% nationally; industry projections (New Telegraph, February 2024) expect national smartphone penetration to reach roughly 60% by 2025. Both support the underlying point, a large share of Nigerians, plausibly still a majority in less urbanised areas, are on basic or feature phones, but neither is precise enough to justify the specific "55-60% in the Southwest" figure, so the deck states it qualitatively instead of citing a number I can't source.
- **The hackathon brief itself**, [osf-hackathon.vercel.app/brief](https://osf-hackathon.vercel.app/brief), for the tracks, judging criteria, operating constraints, and submission requirements.

## Approach to trust and accuracy

I tried to hold the submission materials to the same standard the product itself is built around: don't state something as verified when it isn't. Where I couldn't source a specific number (the Southwest smartphone figure above), I said so and used a qualitative claim instead of a precise one that would look more authoritative than it is.

The product enforces the same discipline structurally, not just as a writing habit:

- **No single report can trigger anything.** A pattern only reaches the security committee once at least 3 distinct senders describe the same behaviour across at least 3 days (5 senders to actually escalate, both values configurable). The one exception is the protected whistleblower channel, where a single report is expected and is explicitly labelled "uncorroborated" rather than treated as verified.
- **Identity content is stripped before an AI ever analyses a report.** Nationality, ethnicity, religion, and "stranger" markers are removed before anything downstream sees the text, so the loudest, most bias-prone signal in a neighbourhood watch (a report that's really about who someone is, not what they did) never reaches the pattern-matching stage.
- **A profiling guard** flags any cluster where more than 60% of its underlying reports needed identity redaction and holds it for manual review, since that shape is closer to suspicion about a person than a verified behavioural pattern.
- **A named-target guard** rejects a report that accuses a specific resident by name rather than describing behaviour, and the refusal reason is retrievable and human-readable, because an unverified accusation reaching a security committee is the single biggest trust failure a system like this could cause.
- **Every escalation carries a structured audit trail:** who decided, on what evidence, when. Nothing is escalated anonymously on the institutional side, even though reporters stay anonymous on theirs.

## AI tool usage

The core idea, the Orogun story, the specific gap in the WhatsApp group, the toll-free SMS approach, the "like Flock cameras, but human intelligence, government-free" framing, and the subnetwork-per-community scaling model, all originated with me, before any AI assistance, in line with the hackathon's rule that the core capstone idea must not be AI-generated.

From that brief, I used Claude (Anthropic's Claude Code, via Cowork) to build the proof of concept: the SMS ingest pipeline, the identity-redaction layer, the channel classifier, the corroboration clustering, the verification desk UI, the profiling guard, the audit trail, and a 35-test automated suite covering the specific failure modes above (a malicious report that shouldn't escalate, a cluster that's mostly redacted content, a dropped webhook that must be retried, and others).

A full, session-by-session log of what was delegated, what was rejected, and where the agent was wrong and how it was caught (including a real bug: an early redaction match false-triggering inside unrelated words like "operatives," caught by eyeballing test output and locked in with a regression test) is in `docs/ai-usage.md` in the repository, updated continuously during the build rather than written after the fact.
