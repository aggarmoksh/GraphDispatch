# Phase 3 Report

All units, incident types, hazards, callers and addresses are SYNTHETIC. Hazard rules are synthetic, not fire-code guidance.

## Tests: 30 passed, 0 failed (previous 21 plus 9 new)
| test | result |
|---|---|
| Phase 1: S1..S6 oracle checks, S7 OutOfArea, latency (8) | pass |
| Phase 2: T1, T2, 30-day window, T3, T4, T5, dispatch twice, latency (8) | pass |
| T6 stroke rule pure-function tests (5) | pass |
| H1 structure_fire, no hazard: HM26 not chosen | pass |
| H2 active oxygen_storage: HM26 chosen, reason has oxygen_storage, base units unchanged, crew note shown | pass |
| H3 expired hazard: HM26 not chosen | pass |
| H4 HM26 assigned: decision records unmet hazmat, base units still returned | pass |
| H5 unknown kind 'unicorns' refused, allowed kinds listed | pass |
| H6 effective_requirements is one db call, required_caps not called | pass |
| extra: hazard kind without adds changes nothing (aggressive_dog, crew note recalled) | pass |
| extra: trauma levels shown (SCVMC pediatric II) without changing hospital choice | pass |
| extra: every query name appears in AGENT.md QUERIES | pass |

One earlier test needed a data change: Phase 2 T2 used hazard kind 'old_hazard', which add_hazard now refuses (required by H5). T2 now uses 'aggressive_dog'; its intent (an expired hazard is not recalled) is unchanged.

## CLI output
H1 (no hazard) and H2 (after an active oxygen_storage hazard), same address "300 Test Way" at 37.3360,-121.8900, graph sjfd_test:
```
H1
Decision dec-2612ea4702 (deterministic-v1) for incident inc-ddb4766fbe [structure_fire, synthetic] at 300 Test Way, status open
Rule: no destination hospital required for structure_fire
Chosen units (synthetic):
  T1    covers ladder            ETA 47 s  [required by incident type]
  E8    covers fire_suppression  ETA 134 s  [required by incident type]
  T8    covers fire_suppression  ETA 134 s  [required by incident type]
  considered for fire_suppression: T1 47s, E8 134s, T8 134s, E30 140s, T30 140s
  considered for ladder: T1 47s, T8 134s, T30 140s, T5 315s, T4 355s
Route legs (intersections): E8=17, T1=6, T8=17
Not dispatched (re-run with --dispatch to confirm).

H2
Decision dec-a6456060a3 (deterministic-v1) for incident inc-facc989b3e [structure_fire, synthetic] at 300 Test Way, status open
Rule: no destination hospital required for structure_fire
Chosen units (synthetic):
  T1    covers ladder            ETA 47 s  [required by incident type]
  E8    covers fire_suppression  ETA 134 s  [required by incident type]
  T8    covers fire_suppression  ETA 134 s  [required by incident type]
  HM26  covers hazmat            ETA 429 s  [added by oxygen_storage]
  considered for fire_suppression: T1 47s, E8 134s, T8 134s, E30 140s, T30 140s
  considered for hazmat: HM26 429s
  considered for ladder: T1 47s, T8 134s, T30 140s, T5 315s, T4 355s
Route legs (intersections): E8=17, HM26=61, T1=6, T8=17
Recalled hazard: oxygen_storage - synthetic: oxygen cylinders
  Crew note: Stored oxygen accelerates fire; no open flame
Recalled earlier incident: inc-ddb4766fbe (structure_fire)
Not dispatched (re-run with --dispatch to confirm).
```
H4 prints "UNMET: hazmat (added by oxygen_storage)" (asserted in the test).

## effective_requirements (one query)
```
MATCH (inc:Incident {incident_id: $incident_id})-[:OF_TYPE]->(t:IncidentType) OPTIONAL MATCH (t)-[q:REQUIRES]->(c1:Capability) WITH inc, t, collect({cap: c1.name, need: q.count, source: 'base'}) AS base OPTIONAL MATCH (inc)-[:AT]->(:Address)<-[:AT]-(h:Hazard)-[:OF_KIND]->(k:HazardKind)-[r:ADDS_REQUIREMENT]->(c2:Capability) WHERE h.valid_from <= $now AND $now <= h.valid_to AND r.incident_type = t.name WITH base, collect({cap: c2.name, need: r.count, source: 'hazard:' + h.hazard_id + ':' + k.name}) AS added UNWIND base + added AS x WITH x WHERE x.cap IS NOT NULL RETURN x.cap AS cap, sum(x.need) AS need, collect(x.source) AS sources ORDER BY cap
```

## reset.py dry run on sjfd (no changes; whole-graph counts identical before and after)
```
graph=sjfd mode=dry run (no changes)
runtime labels:        {'Address': 1, 'Caller': 2, 'Decision': 2, 'Hazard': 1, 'Incident': 2}
runtime relationships: {'AT': 3, 'CALLED_ABOUT': 2, 'CHOSE': 5, 'CONSIDERED': 20, 'DESTINATION': 1, 'FOR': 2, 'NEAREST': 2, 'OF_TYPE': 2, 'RECALLED': 2, 'ROUTE': 132}
seed labels (unchanged): {'Capability': 11, 'HazardKind': 2, 'Hospital': 3, 'IncidentType': 7, 'Intersection': 4213, 'Station': 10, 'Unit': 22}
```
reset --yes on sjfd_test: seed label and relationship counts identical before and after, runtime emptied. A graph other than sjfd or sjfd_test is refused (probe_roads tested, exit 1). reset --yes was never run on sjfd.

## GRAPH.LIST
| graph | nodes, edges | what it is |
|---|---|---|
| sjfd | seed plus runtime | the operator's dispatch graph: seed plus 2 demo incidents, 2 decisions, 1 hazard |
| sjfd_test | seed only after reset | test graph, dropped and reloaded from seed/ every test session |
| probe_roads | 874, 2,145 | Phase 0 probe: old downtown box |
| probe_synth | 5, 7 | Phase 0 synthetic 5-node routing probe |
| probe_procs | 0, 0 | EMPTY: side effect of docs/phases/phase0/probe_procs.py; this is the unexpected fifth graph |

No graph was deleted. sjfd gained 2 HazardKind nodes and 1 ADDS_REQUIREMENT edge because I ran scripts/load.py on it (seed only).

## Latency (20 run_call + why pairs)
| | p50 | p95 | limit |
|---|---|---|---|
| run_call | 33.9 ms | 41.6 ms | 300 ms |
| why() | 3.6 ms | 4.9 ms | 50 ms |

Output is in runs/latency.json (gitignored).

## git status after a full test run
Clean (checked after the commit; the committed docs/phases/phase1/results.json and docs/phases/phase2/latency.json are untouched because tests now write to runs/).

## Flags
- The operator's existing sjfd hazard (haz-d12bc783e4, oxygen_storage) has no OF_KIND edge, so it does not add hazmat. Not fixed.
- A hazard's kind string property is kept alongside the OF_KIND edge.
- The unit candidates query is now keyed by a capability list rather than by IncidentType; behaviour for calls without an incident is unchanged (tests confirm).
- record_decision is still several writes, not one transaction.
- hospitals.csv source_date was left at 2025-08-01; the EMSA list date 2025-08-25 is in the source text.

## Not done
No Bedrock or LLM, agents, MCP, FastAPI, frontend, mutual aid, closures or deployment. No remote or push. reset --yes never run on sjfd. No graph deleted. No change to unit, capability or road seed data. Planning files untouched.
