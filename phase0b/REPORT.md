# Phase 0B Report (2026-10-15)

## boxes.csv
| box | west | south | east | north | hospitals | emergency=yes | fire stations | intersections | edges |
|---|---|---|---|---|---|---|---|---|---|
| B1 | -121.910 | 37.320 | -121.870 | 37.350 | 0 | 0 | 4 | 874 | 2,145 |
| B2 | -121.945 | 37.300 | -121.840 | 37.370 | 5 | 3 | 13 | 4,316 | 10,641 |
| B3 | -121.960 | 37.240 | -121.780 | 37.400 | 10 | 5 | 29 | 17,263 | 41,699 |

POI files: hospitals_raw.csv 10 rows, fire_stations_raw.csv 29 rows (unfiltered).

## Hospitals (B2 and B3)
| name | lat | lon | emergency | boxes |
|---|---|---|---|---|
| Valley Specialty Center | 37.3152 | -121.9333 | (none) | B2, B3 |
| Crestwood San Jose Psychiatric Health Facility | 37.3114 | -121.9151 | (none) | B2, B3 |
| O'Connor Hospital | 37.3281 | -121.9384 | yes | B2, B3 |
| Regional Medical Center of San Jose | 37.3621 | -121.8494 | yes | B2, B3 |
| Santa Clara Valley Medical Center | 37.3135 | -121.9352 | yes | B2, B3 |
| Mission Oaks Hospital | 37.2445 | -121.9482 | no | B3 only |
| Kaiser Permanente San Jose | 37.2401 | -121.8009 | yes | B3 only |
| Good Samaritan Hospital | 37.2522 | -121.9460 | yes | B3 only |
| (no name, osm_id 422727538) | 37.2506 | -121.9503 | (none) | B3 only |
| Children's Healthcare Organization Of Northern California - Pediatric Hospital | 37.2598 | -121.9476 | (none) | B3 only |

Notes: B1 has no hospitals. Kaiser (37.2401) sits right at B3's south edge. The B3 hospitals not in B2 are all in south San Jose.

## AStar
- Signature: dbms.procedures() gives only name and mode. By trial: one config map {sourceNode, targetNode, relTypes, weightProp, latitudeProperty, longitudeProperty}; latitudeProperty/longitudeProperty required (latitudeProp rejected). Attempt 2 of 3 worked.
- Result: **1/20 match** sp_weight within 0.01 s; max abs_diff 104.0 s; AStar weight is 1.0-1.37x SPpaths and never below it (suboptimal paths, probably an inadmissible heuristic). Not investigated.
- Latency (ms): AStar p50 0.73 / p95 1.18; SPpaths p50 0.94 / p95 1.53.
- Acceptance: the "20/20 or logged error" criterion is not met by the letter: the call works but results are wrong; logged in FRICTION_LOG.md.

Final box not chosen (advisor decision).
