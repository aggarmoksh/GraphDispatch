# Phase 7 Report: evaluation

Protocol: `eval/PROTOCOL.md`, pre-registered. Oracle: `eval/oracle.py`. Results: `eval/RESULTS.md`, `eval/results.csv`, `eval/results_raw.json`. All units, incidents and callers are synthetic.

## Commits (protocol first, results second)
| commit | what | time |
|---|---|---|
| `303b997` | PROTOCOL.md, scenarios, oracle, baseline B, frozen prompt for C, oracle tests (no result files) | 2026-10-16T02:39:07-07:00 |
| second commit | run.py, results.csv, results_raw.json, RESULTS.md, this report, docs | see `git log` (its hash cannot be written inside itself) |

`eval/results*` and `eval/RESULTS.md` did not exist when `303b997` was committed (checked with `ls` before and after the commit). No prompt, scenario, oracle or scoring definition changed after it. Two fixes to the report builder in `run.py` (a token-count lookup that crashed and an empty label in the examples) were made after the data was collected; both only changed how results are printed, and the scores come from the code that ran.

## Summary table (correct / applicable)
| metric | A GraphDispatch | B Straight-line | C LLM with facts as text |
|---|---|---|---|
| Exact unit-set match (24) | 24 / 24 | 19 / 24 | 10 / 24 |
| Every required capability covered (24) | 24 / 24 | 23 / 24 | 24 / 24 |
| Hazard-added unit included (O1) | 1 / 1 | 0 / 1 | 1 / 1 |
| Correct hospital (16 scenarios with a destination) | 16 / 16 | 16 / 16 | 14 / 16 |
| Stroke rule applied correctly (4 strokes) | 4 / 4 | 4 / 4 | 4 / 4 |
| Memory recall (O2) | 1 / 1 | 0 / 1 | 1 / 1 |
| Latency median / p95 (ms) | 38.1 / 48.3 | 0.0 / 0.1 | 1274 / 1585 |

A matched the oracle on 24 of 24 under the strict check (same unit set, same capabilities, ETAs within 0.01 s, same hospital and ETA, same recall for O2), so B and C were run. B has no memory or hazard knowledge by definition, so its 0 on the two memory metrics is by construction, not a finding.

## Where each configuration differed from the oracle
- B (5 unit sets): S3, S4, O1, R11, R17. B's straight-line times pick a station that is closer as the crow flies but slower by road. Its hospital choices matched the oracle in all 16 cases, and it applied the stroke rule the same way.
- C (14 unit sets, 2 hospitals): units differed on S2, S4, S5, O1, R01, R03, R04, R06, R08, R10, R11, R12, R14, R17; hospitals differed on R04 (chose Regional, oracle Santa Clara Valley) and R16 (chose Santa Clara Valley, oracle Regional). It included the hazard-added unit on O1 and recalled the memory on O2, because both facts were handed to it as text.

## The 3 worked examples (selected by the protocol's rule; full text in RESULTS.md)
1. S3 (first scenario where B's unit set differs): oracle E3 (als) and M3 (transport), 184 s by road each. B chose E26 and M26 (78 s straight-line, but 210 s by road), because station 26 is nearer by distance and the road to the incident is longer.
2. S2 (first scenario where C differs): oracle E8 for als (217 s by road). C chose E5 (314 s by road). The correct hospital was chosen by all three.
3. S4 (first where both differ): oracle E30 for fire suppression (136 s) and HM26 for hazmat (477 s). B and C both chose E4 (164 s by road; closer in a straight line).

## Bedrock calls, tokens, cost
- Calls in this phase: 24 (limit 26; `runs/llm_calls.log` went from 26 to 50 lines; no transport retry was needed, no errors). pytest made none.
- Tokens for C: 50,969 input and 3,085 output (about 2,123 in and 128 out per scenario).
- Cost: **price not verified.** The AWS Bedrock pricing page loaded but its Anthropic on-demand table was not in the page text I could read (only an unnamed example at $0.008 per 1K input and $0.024 per 1K output), so no figure is claimed.

## What this does and does not show
- Road-time routing is what separates A from B on unit choice (24 versus 19 of 24). A system with coordinates and no roads is right on the hospital in every scenario here, because the three hospitals were ordered the same way by straight line and by road; this set therefore does not show a hospital-choice benefit from the graph.
- A model given every fact as text but no road network is poor at estimating who is fastest (10 of 24), and slower (about 1.3 s versus 38 ms), but it applied the hazard and memory facts correctly when they were put in its prompt (O1, O2). On this evidence the graph's advantage on memory is that recall and requirements are stored, queried and deterministic (A is exact by construction), not that a model cannot use the facts when handed them. The two memory scenarios are too few to claim more.
- The stroke-rule scenarios did not discriminate: all three configurations chose Regional or the same hospital as the oracle in all four strokes.
- 24 synthetic scenarios, temperature 0, one run. A and the oracle share rules written by one author; the oracle is independent in code and method and its numbers were confirmed separately, but it does not test whether the rules are right.

## Tests
81 passed, 0 failed (72 earlier plus 9 in `tests/test_oracle.py`). Oracle tests on the advisor-confirmed numbers all pass: S1 E7/M7 132 s, Regional 551 s, O'Connor 49 s, Santa Clara Valley 140 s; at 37.336,-121.89 T1 47 s, HM26 429 s, O'Connor 352 s. A check parses `oracle.py` and fails if it imports anything but the standard library and networkx. The grep shows no `import graphdispatch` or `from graphdispatch` in `eval/oracle.py`, `prompt.py`, `baselines.py` or `make_scenarios.py` (the only mention is a docstring).

## Files created
`eval/PROTOCOL.md`, `eval/prompt_template.txt`, `eval/prompt.py`, `eval/oracle.py`, `eval/baselines.py`, `eval/make_scenarios.py`, `eval/scenarios.json`, `eval/run.py`, `eval/results.csv`, `eval/results_raw.json`, `eval/RESULTS.md`, `tests/test_oracle.py`, `phase7/REPORT.md`; `AGENT.md`, `POSTLAUNCH.md`, `AI_DISCLOSURE.md`, `FRICTION_LOG.md` updated.

## Flags
- Before the phase started, `deploy/iam-bedrock-policy.json` had been changed on disk by the operator (a second statement, an extra action, a real account id). That broke `test_iam_policy_allows_only_invoke_on_haiku_45`. The operator confirmed it was intentional, so I did not stop; I updated that one test in the working tree to the new two-statement shape. Neither file is in my commits, so the operator decides whether to commit the account id.
- `phase4a/intake_results.csv` is still modified in the working tree (the operator's rerun) and is not committed.
- The scenarios fix E1 and M1 as available (the seed marks them busy) for the whole evaluation; this is stated in the protocol.

## Not done
No deployment, UI change, closures or mutual aid, no prompt tuning, no retry beyond the protocol (none was needed). No git remote or push, no AWS changes, no `reset --yes` on sjfd, planning files untouched.
