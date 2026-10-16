# Phase 1 Report

Units and incident types are SYNTHETIC. Hospital capabilities come from seed/hospitals.csv (sourced, dated).

## Build
- SCC cut (B2): nodes 4,316 to 4,213; edges 10,641 to 10,472; CSV edges after parallel dedupe 10,430 (42 dropped).
- Graph "sjfd" counts: Intersection 4,213; Station 10; Hospital 3; Unit 22; Capability 11; IncidentType 7. ROAD 10,430; LOCATED_AT 13; BASED_AT 22; HAS_CAPABILITY 43; OFFERS 10; REQUIRES 14; DESTINATION_NEEDS 5.
- load.py rerun: output byte-identical (all counts and snap distances).
- point() and distance(): both work (meters, float32).

## snap_m (all under 300 m)
| Hospital | snap_m | Station | snap_m |
|---|---|---|---|
| Santa Clara Valley Medical Center | 16.9 | 1 | 45.7 |
| Regional Medical Center of San Jose | 151.9 | 3 | 41.0 |
| O'Connor Hospital | 118.4 | 4 | 135.1 |
| | | 5 | 94.4 |
| | | 6 | 39.0 |
| | | 7 | 111.9 |
| | | 8 | 33.1 |
| | | 10 | 73.8 |
| | | 26 | 85.9 |
| | | 30 | 34.5 |

## Scenarios (ETAs in seconds; all assertions pass, 8 tests green)
| # | type | units (capability, ETA) | chosen hospital | nearest hospital | differs | skipped reason | ms |
|---|---|---|---|---|---|---|---|
| S1 | stroke | E7 als 132.3; M7 transport 132.3 | Regional | O'Connor | yes | O'Connor nearest (49 s), lacks stroke_thrombectomy | 42.4 |
| S2 | burn | E8 als 217.5; M5 transport 314.3 | Santa Clara Valley MC | Regional | yes | Regional nearest (84 s), lacks burn | 30.8 |
| S3 | cardiac_arrest | E8 als 134.3; M3 transport 149.7 | O'Connor | O'Connor | no | none | 28.8 |
| S4 | structure_fire | E8 fire_suppression 51.5; T8 ladder 51.5; T1 fire_suppression 122.0 | n/a | n/a | n/a | n/a | 18.3 |
| S5 | pediatric_trauma | E3 als 184.5; M3 transport 184.5 | Santa Clara Valley MC | Regional | yes | Regional nearest (508 s), lacks pediatric_trauma | 21.4 |
| S6 | hazmat_spill | E30 fire_suppression 135.9; HM26 hazmat 477.1 | n/a | n/a | n/a | n/a | 14.9 |
| S7 | cardiac_arrest at 37.45,-121.90 | raises OutOfArea | | | | | |

Assertion checks: every unit ETA and hospital ETA equals the networkx oracle within 0.01 s (oracle snaps independently by haversine); chosen units available and carry the covered capability; required counts met; chosen hospital offers the destination capability and is the fastest such; S7 raises.

## Latency (6 scenarios x 5 runs, S7 excluded)
p50 18.3 ms, p95 22.3 ms (limit 300 ms). Numbers are in docs/phases/phase1/results.json.

## networkx grep
Runtime code (graphdispatch/, scripts/) has no networkx import. Imports found: tests/test_recommend.py and docs/phases/phase0/compare.py. The latter is the committed Phase 0 probe, outside tests/, so the literal "only under tests/" check does not hold. Flagged, not moved.

## Flags
- Stale OSM operator tags (Regional=HCA, O'Connor=Verity Health).
- scripts/load.py reads hospital coordinates from data/processed/hospitals_raw.csv, which is gitignored (seed/hospitals.csv has no coordinates, per the spec).
- Greedy assignment order is scarcest capability first; the spec said "for each required capability", so this ordering is my choice (documented in AGENT.md).
- Friction entries for this phase were written after the work, not live.

## Not done
No LLM calls, agents, MCP, memory/hazards, provenance, mutual aid, FastAPI, frontend or AStar. No remote or push. probe_roads and probe_synth untouched. Planning files untouched. No capability or unit data changed.
