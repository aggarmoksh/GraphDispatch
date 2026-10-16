# Phase 2 Report

All units, incident types, callers, addresses, hazards and incidents are SYNTHETIC. Timestamps are epoch seconds.

## Tests (21 passed, 0 failed; graph sjfd_test, loaded fresh from seed/)
| file | test | result |
|---|---|---|
| test_memory | T1 repeat address recalls hazard and prior incident (second Decision has RECALLED to both) | pass |
| test_memory | T2 expired hazard not recalled | pass |
| test_memory | prior incident older than 30 days not recalled | pass |
| test_provenance | T3 why() equals recommend() for S1 (units, ETAs, DESTINATION, SKIPPED, rule text, ROUTE contiguity, ROAD edge per step, route weight = ETA) | pass |
| test_provenance | T4 dispatch S4, second call picks none of the assigned units, clear restores all statuses | pass |
| test_provenance | T5 unit made 'assigned' between record and dispatch: refused, no change | pass |
| test_provenance | dispatch twice refused | pass |
| test_provenance | latency (20 calls) | pass |
| test_rules | T6 stroke rule: within limits, extra too large, total too large, boundaries inclusive, missing hospital | pass x5 |
| test_recommend | Phase 1 S1..S6 oracle checks and S7 OutOfArea, plus latency | pass x8 |

## Fresh clone
Cloned the committed repo to %TEMP%\gd_clone (no data/ folder present), ran its scripts/load.py with GRAPH_NAME=sjfd_clonecheck. Counts identical to sjfd:
- Nodes: Capability 11, Hospital 3, IncidentType 7, Intersection 4,213, Station 10, Unit 22.
- Relationships: BASED_AT 22, DESTINATION_NEEDS 5, HAS_CAPABILITY 43, LOCATED_AT 13, OFFERS 10, REQUIRES 14, ROAD 10,430.
Deleted only graph sjfd_clonecheck and the clone folder.

## why() for S1 (stroke at 37.33,-121.93), printed in full
```
Decision dec-fe85b45155 (deterministic-v1) for incident inc-d0ba1a003f [stroke, synthetic] at 1 Stroke St, status open
Rule: Regional Medical Center of San Jose +502 s over O'Connor Hospital, within 1800 s AHA bypass limit (total 551 s <= 2700 s; AHA Mission: Lifeline Stroke EMS algorithm)
Chosen units (synthetic):
  E7    covers als               ETA 132 s
  M7    covers transport         ETA 132 s
  considered for als: E7 132s, M7 132s, E10 157s, M10 157s, E4 168s
  considered for transport: M7 132s, M10 157s, M5 302s, M3 407s, M26 639s
Destination: Regional Medical Center of San Jose (ETA 551 s)
  skipped O'Connor Hospital (49 s): O'Connor Hospital lacks stroke_thrombectomy (nearest)
  skipped Santa Clara Valley Medical Center (140 s): Santa Clara Valley Medical Center lacks stroke_thrombectomy
Route legs (intersections): E7=16, M7=16, hospital=46
```

## T1 recall output
```
{'incidents': [{'incident_id': 'inc-e218fa808b', 'type': 'cardiac_arrest', 'created_at': 1792113361, 'status': 'open'}],
 'hazards': [{'hazard_id': 'haz-67e7543ab7', 'kind': 'oxygen_storage', 'note': 'synthetic: oxygen cylinders in garage', 'valid_from': 1792113361, 'valid_to': 1794705361}]}
```
(The second call used the label "  100   EXAMPLE ave "; the address id normalizes to the same Address.)

## Latency (20 run_call + why pairs, last run)
| | p50 | p95 | limit |
|---|---|---|---|
| why() | 4.5 ms | 9.2 ms | 50 ms |
| run_call | 38.4 ms | 57.6 ms | 300 ms |

## Read functions and the method they call
| function | method |
|---|---|
| recommend.snap, recommend.recommend (_eta, _route) | db.read (GRAPH.RO_QUERY) |
| ops.recall | db.read |
| ops.why | db.read, one query |
| ops.dispatch (refusal diagnosis only, after the write) | db.read; the dispatch itself is db.write |
| ops.create_incident | db.read (snap), then db.write |
| scripts/load.py counts and snap_report | db.read |
| write paths: create_incident, add_hazard, record_decision, dispatch, clear, loaders | db.write (GRAPH.QUERY) |

## grep: networkx
No match under graphdispatch/ or scripts/. It is imported only in tests/ and the exempt phase0 probe.

## Graph counts
sjfd (seed data only): same as the fresh-clone list above.
sjfd_test after the last CLI demo call (runtime nodes included): Address 1, Caller 1, Decision 1, Incident 1, plus the seed nodes above; relationships AT 1, CALLED_ABOUT 1, CHOSE 2, CONSIDERED 10, DESTINATION 1, FOR 1, NEAREST 1, OF_TYPE 1, ROUTE 78, SKIPPED 2, plus the seed relationships above. Tests wipe runtime nodes before every test, so these numbers reflect only that last call.

## Flags
- Added Unit-[:ASSIGNED_TO]->Incident beyond the Phase 2 model, so clear() frees only units dispatched to that incident.
- record_decision is several write queries, not one transaction.
- incident_types.csv gained four columns (fallback_capability, max_extra_s, max_total_s, rule_source) to carry the stroke rule; unit and capability seed data unchanged.
- Scarcest-capability-first assignment (Phase 1 choice) is unchanged.
- phase1/results.json and phase2/latency.json are rewritten by the test runs, so they churn in git.
- SKIPPED lists every faster hospital that was passed over, not only the nearest.

## Not done
No LLM or Bedrock calls, agents, MCP, FastAPI, frontend, mutual aid, road closures or deployment. No remote or push. sjfd was loaded by the new loader but never written by tests. Planning files untouched.
