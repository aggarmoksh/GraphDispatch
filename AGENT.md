# GraphDispatch - Project Brief

Graph Hacks (WeMakeDevs x FalkorDB), Tracks 01 and 02.

## Stack
- Python 3.12, falkordb-py
- FalkorDB in Docker for dev
- FastAPI + Next.js later, not now

## Decisions
- networkx is a test-only oracle and must never be imported by runtime code.
- All Cypher is parameterized, never f-strings.
- Indexes are created before bulk loads.
- Map box is B2 (W -121.945 S 37.300 E -121.840 N 37.370), largest strongly connected component only (4,213 intersections).
- graphdispatch/db.py is the only module that talks to FalkorDB; every runtime query is named in graphdispatch/queries.cypher.
- Hospitals are matched by osm_id, never by name (O'Connor's OSM name has a curly apostrophe).
- Units and incident types are synthetic and labeled so (synthetic:true, "# synthetic" in the seed headers).
- Routing is algo.SPpaths on travel_s; AStar is not used.
- Unit assignment is greedy, scarcest capability first (fewest available candidate units, ties by name), fastest units first, a unit counted once.
- Hospital choice: fastest ETA among hospitals that OFFER the destination capability; the nearest hospital of any kind is reported with the reason it was skipped.
- Incidents more than 500 m from the nearest intersection raise OutOfArea.
- LLM provider for Phase 3 will be Amazon Bedrock behind an adapter (nothing LLM-related exists yet).
- Graph name comes from env GRAPH_NAME (default sjfd). Tests use sjfd_test, dropped and reloaded from seed/ at session start; tests never write to sjfd.
- scripts/load.py reads ONLY from seed/ (road snapshot seed/osm_b2_<date>/); build_roads.py writes a new snapshot folder only with --refresh.
- All reads go through db.read (GRAPH.RO_QUERY); writes through db.write. recommend() is read-only.
- why(decision_id) is ONE Cypher query. dispatch(decision_id) is ONE query: units flip to assigned only if all chosen units are available, else no rows and no change. Dispatch is human-confirmed; run_call never dispatches.
- Stroke destination rule lives on the stroke DESTINATION_NEEDS edge (fallback, max_extra_s, max_total_s, source) and is applied by the pure function rules.stroke_bypass.
- Timestamps are epoch seconds (int). Address id is the label lowercased with whitespace collapsed. Recall window is 30 days; hazards recalled when valid_from <= now <= valid_to.
- Acceptance rule: no networkx under graphdispatch/ or scripts/ (tests/ and the phase0 probe are exempt).
- Hospital capabilities come from seed/hospitals.csv (sources and dates recorded per row); OSM operator tags are not used.

## Pitfalls
- Verify engine behavior on a live FalkorDB before relying on researched claims.
- Check the installed osmnx bbox argument order before calling graph_from_bbox (2.x: one tuple of left, bottom, right, top).
- Use py -3.12 for the venv; the default python on this machine is 3.10.
- Call algo.SPpaths with a single config map and a pathCount; algo.AStar takes one argument (a config map), not (source, target, config).
- GRAPH.MEMORY USAGE reports whole MB (0 for small graphs); use INFO memory used_memory deltas for small graphs.
- algo.AStar takes one config map and requires latitudeProperty and longitudeProperty (not latitudeProp). With weightProp travel_s it returned suboptimal paths (1/20 match); do not use it for routing without re-verification. dbms.procedures() returns only name and mode, no signatures.
- Reading OSM features and drive graphs for the large box takes minutes; run in background.
- Engine default query TIMEOUT is 1000 ms (FalkorDB 4.22.1 module).
- The downtown San Jose bbox yields 874 intersections, below the 1,000 floor; revisit the bbox before relying on it.

## Graph model (graph "sjfd")
```mermaid
graph LR
  I1[Intersection osm_id lat lon loc] -->|ROAD travel_s length_m name| I2[Intersection]
  S[Station station_id name agency] -->|LOCATED_AT snap_m| I1
  H[Hospital osm_id name source source_date] -->|LOCATED_AT snap_m| I1
  H -->|OFFERS| C[Capability name]
  U[Unit unit_id type status synthetic] -->|BASED_AT| S
  U -->|HAS_CAPABILITY| C
  T[IncidentType name synthetic] -->|REQUIRES count| C
  T -->|DESTINATION_NEEDS fallback max_extra_s max_total_s source| C
  INC[Incident incident_id type lat lon created_at status synthetic] -->|OF_TYPE| T
  INC -->|AT| AD[Address address_id label lat lon]
  INC -->|NEAREST| I1
  CL[Caller caller_id] -->|CALLED_ABOUT at| INC
  HZ[Hazard hazard_id kind note valid_from valid_to created_at] -->|AT| AD
  HZ -->|REPORTED_IN| INC
  U -->|ASSIGNED_TO| INC
  D[Decision decision_id ts agent rule_applied] -->|FOR| INC
  D -->|CONSIDERED capability eta_s rank| U
  D -->|CHOSE capability eta_s| U
  D -->|DESTINATION eta_s| H
  D -->|SKIPPED reason eta_s| H
  D -->|ROUTE leg seq| I1
  D -->|RECALLED| HZ
  D -->|RECALLED| INC
```
ASSIGNED_TO (Unit to Incident) is an addition beyond the original spec, so clear() frees only units dispatched to that incident.

## Phase 1 pitfalls
- point() and distance() work on FalkorDB 4.22.1 (distance in meters, float32 precision).
- In osmnx 2.1.1 the SCC function is ox.truncate.largest_component(G, strongly=True).
- B2 SCC cut drops 103 nodes; CSV export also drops 42 parallel edges.
- OSM operator tags are stale: Regional shows HCA and O'Connor shows Verity Health, both are county-run now. Do not trust them.
- scripts/load.py reads hospital coordinates from data/processed/hospitals_raw.csv (gitignored), so run Phase 0B fetch_pois.py first on a fresh clone.
- Long multi-file shell heredocs failed once in this shell; write files with the editor tool.

## Phase 2 pitfalls
- ro_query works with CALL algo.SPpaths; use it for all reads.
- OPTIONAL MATCH + collect({...}) returns one all-null map when nothing matches; filter in Python. UNWIND over an empty list drops all rows, so skip empty writes.
- record_decision is several write queries (not one transaction); a crash mid-way can leave a partial decision.
- Test helper queries (wipe_runtime, set_unit_status) live in queries.cypher; drop_graph and wipe are guarded to *_test graphs only.
- Fresh clone: python scripts/load.py (with GRAPH_NAME set) needs only seed/ and a running FalkorDB.

## Anti-features
- Voice input
- Multilingual intake
- Auth/accounts
- Full Bay Area road network
- Graphiti/Cognee as memory layer
- Mobile apps
- Real 911 or personal data

## Privacy
- Synthetic and public OSM data only. No personal data, no real emergency traffic, no keys in tracked files.