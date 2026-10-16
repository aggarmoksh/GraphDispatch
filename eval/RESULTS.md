# Phase 7 results

Protocol: eval/PROTOCOL.md (commit 303b997). Scoring against eval/oracle.py. Results are reported as produced.

## Summary (correct / applicable)

| metric | A GraphDispatch | B Straight-line | C LLM with facts as text |
|---|---|---|---|
| Exact unit-set match (24) | 24 / 24 | 19 / 24 | 10 / 24 |
| Every required capability covered (24) | 24 / 24 | 23 / 24 | 24 / 24 |
| Hazard-added unit included (O1) | 1 / 1 | 0 / 1 | 1 / 1 |
| Correct hospital | 16 / 16 | 16 / 16 | 14 / 16 |
| Stroke rule applied correctly (4 strokes) | 4 / 4 | 4 / 4 | 4 / 4 |
| Memory recall (O2) | 1 / 1 | 0 / 1 | 1 / 1 |
| Latency median / p95 (ms) | 38.1 / 48.3 | 0.0 / 0.1 | 1274.3 / 1585.0 |

## Configuration C usage

- Bedrock calls in this phase: 24 (limit 26). Input tokens 50,969, output tokens 3,085 (2,123 in and 128 out per scenario).
- Price not verified (the AWS Bedrock pricing page could not be reached): tokens only.
- C errors: none

## Per scenario (unit set / hospital correct)

| scenario | type | A | B | C |
|---|---|---|---|---|
| S1 | stroke | units ok, hospital ok | units ok, hospital ok | units ok, hospital ok |
| S2 | burn | units ok, hospital ok | units ok, hospital ok | units differ, hospital ok |
| S3 | pediatric_trauma | units ok, hospital ok | units differ, hospital ok | units ok, hospital ok |
| S4 | hazmat_spill | units ok | units differ | units differ |
| S5 | structure_fire | units ok | units ok | units differ |
| O1 | structure_fire | units ok | units differ | units differ |
| O2 | cardiac_arrest | units ok, hospital ok | units ok, hospital ok | units ok, hospital ok |
| R01 | structure_fire | units ok | units ok | units differ |
| R02 | cardiac_arrest | units ok, hospital ok | units ok, hospital ok | units ok, hospital ok |
| R03 | stroke | units ok, hospital ok | units ok, hospital ok | units differ, hospital ok |
| R04 | major_trauma | units ok, hospital ok | units ok, hospital ok | units differ, hospital differs |
| R05 | pediatric_trauma | units ok, hospital ok | units ok, hospital ok | units ok, hospital ok |
| R06 | burn | units ok, hospital ok | units ok, hospital ok | units differ, hospital ok |
| R07 | hazmat_spill | units ok | units ok | units ok |
| R08 | structure_fire | units ok | units ok | units differ |
| R09 | cardiac_arrest | units ok, hospital ok | units ok, hospital ok | units ok, hospital ok |
| R10 | stroke | units ok, hospital ok | units ok, hospital ok | units differ, hospital ok |
| R11 | major_trauma | units ok, hospital ok | units differ, hospital ok | units differ, hospital ok |
| R12 | pediatric_trauma | units ok, hospital ok | units ok, hospital ok | units differ, hospital ok |
| R13 | burn | units ok, hospital ok | units ok, hospital ok | units ok, hospital ok |
| R14 | hazmat_spill | units ok | units ok | units differ |
| R15 | structure_fire | units ok | units ok | units ok |
| R16 | cardiac_arrest | units ok, hospital ok | units ok, hospital ok | units ok, hospital differs |
| R17 | stroke | units ok, hospital ok | units differ, hospital ok | units differ, hospital ok |

## Worked examples (selected by the protocol's rule)

### S3: pediatric trauma (first scenario where B's unit set differs)

Incident pediatric_trauma at 37.31, -121.86

- Oracle: units E3 for als (184 s by road), M3 for transport (184 s by road); hospital Santa Clara Valley Medical Center (524 s)
- A GraphDispatch: units E3 for als (184 s by road), M3 for transport (184 s by road); hospital Santa Clara Valley Medical Center
- B Straight-line: units E26 for als (78 s straight-line), M26 for transport (78 s straight-line); hospital Santa Clara Valley Medical Center
- C LLM with facts as text: units E3 for als, M3 for transport; hospital Santa Clara Valley Medical Center
- Why the oracle differs from B: B chose E26 (road time 210 s), which the oracle did not; B chose M26 (road time 210 s), which the oracle did not; the oracle chose E3 for als (road time 184 s), which B did not; the oracle chose M3 for transport (road time 184 s), which B did not.

### S2: burn, east side (first scenario where C's unit set or hospital differs)

Incident burn at 37.36, -121.855

- Oracle: units E8 for als (217 s by road), M5 for transport (314 s by road); hospital Santa Clara Valley Medical Center (608 s)
- A GraphDispatch: units E8 for als (217 s by road), M5 for transport (314 s by road); hospital Santa Clara Valley Medical Center
- B Straight-line: units E8 for als (184 s straight-line), M5 for transport (297 s straight-line); hospital Santa Clara Valley Medical Center
- C LLM with facts as text: units E5 for als, M5 for transport; hospital Santa Clara Valley Medical Center
- Why the oracle differs from C: C chose E5 (road time 314 s), which the oracle did not; the oracle chose E8 for als (road time 217 s), which C did not.

### S4: hazmat spill (first scenario where both differ (not already shown))

Incident hazmat_spill at 37.32, -121.91

- Oracle: units E30 for fire_suppression (136 s by road), HM26 for hazmat (477 s by road); hospital none
- A GraphDispatch: units E30 for fire_suppression (136 s by road), HM26 for hazmat (477 s by road); hospital none
- B Straight-line: units E4 for fire_suppression (98 s straight-line), HM26 for hazmat (417 s straight-line); hospital none
- C LLM with facts as text: units HM26 for hazmat, E4 for fire_suppression; hospital none
- Why the oracle differs from B: B chose E4 (road time 164 s), which the oracle did not; the oracle chose E30 for fire_suppression (road time 136 s), which B did not.
- Why the oracle differs from C: C chose E4 (road time 164 s), which the oracle did not; the oracle chose E30 for fire_suppression (road time 136 s), which C did not.

## Reading these numbers

- 24 synthetic scenarios and one temperature-0 run are a demonstration, not a statistical study (protocol section 10).
- A and the oracle share rules written by the same author; the oracle differs in code and method, and its numbers were confirmed independently, but this does not test whether the rules are medically right.
- C had every fact as text but no road network, by design. B had the same tables with straight-line distances and no memory.
