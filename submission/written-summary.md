Written summary: Àkíyèsí

Andela x Open Society Foundations Hackathon, "Information you can trust." Submitted by Fehintoluwa Dahunsi, Nigeria, solo.

THE SIGNAL WAS ALWAYS THERE

When I moved into the Orogun neighbourhood in Ibadan, burglaries had been rising nearby, and a tip said the gang behind them was coming to our street next. The neighbourhood responded fast: barrier gates, a curfew, Amotekun (the regional security outfit) hired to guard the streets, and a WhatsApp group to collect tips and push information back out.

It worked, up to a point. But a WhatsApp group runs on smartphones and data, and the people closest to the street at 2am, night guards, okada riders, traders, are often not in it. Pew Research Center's most recent global survey, fielded in 2023, found that fewer than half of Nigerian adults own a smartphone, among the lowest shares of any country surveyed, which points at the gap I saw. The group also offers no anonymity, so nobody can report a guard or a committee member without fear of reprisal, and it cannot turn many one-off remarks into anything a committee can act on.

That last gap is the heart of the idea. One person noticing men unloading sacks at night, or a car that keeps parking outside the same house, has noticed nothing worth posting. But dozens of such observations, from different people on different nights, spread over weeks, add up to a pattern no single person holds. The information is not missing. It is scattered, and there is no aggregator.

Àkíyèsí (Yoruba for "observation, taking notice") is built to be that aggregator. A resident texts a toll-free number from any phone, including a basic feature phone, and says what they saw, roughly when and where. The system strips identity language, sets aside noise like a loud party or a lost goat, and groups reports that describe the same emerging pattern. Only when enough separate people, over enough days, have noticed the same thing does the neighbourhood's own security committee receive a structured brief, never a raw message thread and never on one report. A separate anonymous line lets residents report the security apparatus itself. Nothing is published: no public map, list or feed, which is the difference from incident-mapping platforms in the mould of Ushahidi.

The same design reaches beyond burglary. On 16 January 2024, an explosion in Bodija, Ibadan, injured 77 people, killed two or three depending on the source, and affected more than 20 buildings; the governor said illegal miners occupying a house there had stored explosives in it. I cannot know what neighbours noticed beforehand, but unfamiliar drums offloaded at night or a chemical smell are the small signs a residential street sees first. The same pipeline with a different pattern definition is built to make them add up sooner.

It scales by repetition: each community gets its own number and committee, and adding one is a configuration row, not new code. The cost is real: it only works where a functioning committee exists to receive the signal.

TRACK

Primary: Stability & Social Cohesion. The brief describes this track as reducing everyday friction and keeping tensions from escalating into conflict. Gates, a curfew and armed guards were a response to fear, and acting on a wrong guess about a stranger is how fear turns into confrontation. Àkíyèsí lets a community learn what is actually happening before it acts.

Secondary: Safety, Reporting & Protection. The brief asks for safe reporting with anonymity and clear pathways to action. The protected channel serves the hardest report in a small community, one about a gateman, hired guard or committee member. It goes to a separate recipient, the landlord association, and the committee's own desk can never see it.

INFORMATION SOURCES

Everything Àkíyèsí acts on comes from a person on the ground, in their own words, describing something they personally saw. Nothing is scraped, bought or passed on secondhand. Because no single account is trusted, a signal is the same behaviour reported by several distinct senders over several days, and every brief says how many senders are behind it, over how many days, and which pattern they matched, so the committee can see what it rests on. Reports are stored as redacted text with a salted hash of the sender, not a phone number. Patterns live in data files: burglary casing from Orogun, explosives storage from Bodija, and weapon sightings.

Facts in this submission come from my own account of the Orogun response; TheCable (https://www.thecable.ng/seyi-makinde-two-dead-77-injured-in-ibadan-explosion-caused-by-illegal-miners/) and VOA (https://www.voanews.com/a/killed-77-injured-in-massive-blast-in-southern-nigerian-city-/7443585.html) for Bodija; Pew Research Center (https://www.pewresearch.org/short-reads/2024/02/05/8-charts-on-technology-use-around-the-world/) for smartphone ownership; and the hackathon brief. The demonstration data is entirely synthetic: 60 reports over six weeks in two demonstration communities, including noise that should not cluster and an accusation against a named neighbour. A seven-report Bodija-style replay illustrates the mechanism. It is not evidence that the real event would have been prevented.

APPROACH TO TRUST AND ACCURACY

A single account can be mistaken, malicious or shaped by fear, and where there is a curfew and armed guards, acting on a wrong one lands on a real person. So Àkíyèsí never asks anyone to trust one report, and builds the risky decisions into its structure.

Corroboration first. On the general line, a pattern becomes visible to the committee only when at least 3 distinct senders describe it across at least 3 days, and can be escalated only at 5. Fifteen reports from one phone count as one sender. Weapon sightings have a faster path: one report shows as a priority item for a person to look at, and escalation needs two senders across a day. The protected line is the one deliberate exception, since a whistleblower is by definition alone: one report goes to the protected recipient, labelled uncorroborated.

Identity stripped first. Intake asks what was seen, not who, but no script controls what a frightened person types, and with a curfew in force the most natural report is a stranger out late. Nationality, ethnicity, tribe, religion and stranger language are removed before anything is analysed, so what moves forward is a description of an action, not a person.

Two guards cover what redaction cannot. A profiling guard holds any cluster for manual review if more than 60 percent of its reports needed redaction, since that is suspicion of a person rather than observation of behaviour. A named-target guard keeps any report accusing a specific resident out of clustering, with the reason recorded in plain language.

People decide, on the record. The software never escalates on its own. A committee member acts from a verification desk, and each escalation records who decided, on what evidence, when. Every cluster shows when it was last updated and how old it is, and the desk shows dates rather than clock times, because in a neighbourhood of a few hundred people exact times can identify who reported.

USE OF AI TOOLS

The core idea, the Orogun story, the WhatsApp gap, the toll-free SMS approach and the one-number-per-community scaling model all came from me before any AI assistance, in line with the brief's rule that AI should not generate the capstone idea.

I then used Claude (Anthropic's Claude Code, via Cowork) to build the proof of concept: SMS-shaped intake, redaction, channel classification, clustering, the verification desk and audit trail, both guards, a browser console and a presenter remote for running the demonstration, Yoruba support, and a 147-test suite that currently passes. I worked from a written brief and kept the risky decisions. When I asked for a faster path for weapon reports, Claude set out three options and flagged that a true single-report bypass would contradict the design's own rule that no single report triggers anything. I chose the option that lowers the threshold but keeps a person in the loop.

Tests and close reading caught the agent's errors. An early redaction rule matched the ethnicity term "Tiv" inside the word "operatives"; it surfaced while reading replay output by eye, and a regression test now pins it. A proposed weapon keyword, "armed men", would have matched inside "unarmed men"; Claude caught it before it shipped and pinned it the same way. The full log of what was delegated, rejected and got wrong is in docs/ai-usage.md, every model prompt is a versioned file under prompts/, and commit messages describe intent. In the product itself, Claude reads every message through the Anthropic API for redaction, classification and pattern extraction. The rule-based word lists stay underneath as a floor, so anything on a list is removed even if the model misses it, and as a fallback if the API fails. The accusation check and the corroboration thresholds are fixed rules, never a model call, and the test suite runs on the rule-based version so it is repeatable.

WHERE IT GOES NEXT

Voice is next and needs nothing new from a reporter: the same number, but they call and leave a recorded message that is transcribed. It is not built yet. After that come a formal handoff from the committee to law enforcement for the patterns that warrant it, more reliable pattern matching, and more communities and languages, each a configuration row. A real toll-free number goes through the telecom regulator and an SMS aggregator, so the proof of concept receives messages through a provider-shaped webhook and a simulated inbound endpoint instead.

The signal was always there. It just had nowhere to go.
