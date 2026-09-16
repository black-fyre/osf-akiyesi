# Pattern extraction prompt -- v1 -- en-NG

Used by `app.llm.VertexGeminiClient.score_patterns` (production). The
rule-based client (what this iteration runs) implements the same contract
as keyword scoring against `config/patterns.yaml` -- see
`app/extraction.py`.

## System instruction

You are given an already-redacted resident observation and a list of
named behaviour patterns, each with a short description. Score how
strongly the observation matches EACH pattern, as an integer count of
distinct pieces of evidence in the text supporting that pattern (0 if
none).

Patterns are supplied at call time from `config/patterns.yaml` -- do not
rely on a fixed list; a new pattern definition (e.g. a different kind of
hazard, a different casing behaviour) must be scoreable without a prompt
change, only a config change (CLAUDE.md scalability seam #3: "pattern
definition is data, not logic").

A report that is ambient neighbourhood noise -- a noise complaint, a lost
pet, an interpersonal argument with no security-relevant behaviour -- should
score 0 against every supplied pattern. Do not force a low-confidence match;
an unmatched report is filed as `unclassified` and deliberately excluded
from corroboration, which is the mechanism that keeps noise from diluting a
real pattern's signal.

## Output contract

Return `{"scores": {"<pattern_id>": <int>, ...}}` for every pattern_id
supplied, plus (best-effort, may be null) `{"time_of_day": "night" | "early_morning" | "afternoon" | "evening" | null}`
based on any time reference in the text.

## Worked example

Patterns supplied: `burglary_casing`, `explosives_storage`.

Input: `"Someone was checking gates along Alade Street block by block late last night."`

Output:
```json
{"scores": {"burglary_casing": 1, "explosives_storage": 0}, "time_of_day": "night"}
```
