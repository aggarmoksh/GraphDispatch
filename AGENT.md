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
- Design rule: the LLM never writes Cypher. It may only output values from enums derived from the graph (IncidentType names, HazardKind names), via forced tool calls whose schemas are built at runtime from the graph. The caller text is data, not instructions.
- LLM provider: Amazon Bedrock Converse API behind graphdispatch/llm.py (region us-east-1; model us.anthropic.claude-haiku-4-5-20251001-v1:0, chosen because Haiku 5.5 returned AccessDeniedException for this account). Hard cap LLM_CALL_CAP calls per process (default 20). Credentials live only in the gitignored .env or the AWS chain; never printed or committed.
- Address ids are normalized (lowercase, punctuation stripped, whitespace collapsed, last word abbreviated via seed/address_suffixes.csv), so "200 Demo Street" and "200 demo st." are one Address. Device-derived labels are "device@<lat 4dp>,<lon 4dp>".
- LLM intake (graphdispatch/intake.py): text -> one forced classify_call -> validation against the graph's enums in code (IntakeRejected, nothing written) -> create incident (call_text and intake_model stored, synthetic) -> caller-reported hazards written as Hazard {reported_by:'caller'} -> effective_requirements -> recommend -> record_decision. Never dispatches. The model's confidence is uncalibrated (0.95 everywhere in the 4A probe) and is neither stored nor shown.
- MCP (graphdispatch/tools.py + mcp_server.py, SDK package `mcp` 2.3.0): exactly six tools; five are read-only and report_hazard is the only write. There is no dispatch tool, no clear tool and no tool that takes Cypher or free query text. Dispatch stays human-confirmed (CLI/ops).
- Memory changes decisions: requirements for an incident are the type's REQUIRES plus ADDS_REQUIREMENT from active hazards at the same Address whose incident_type matches (query effective_requirements, one query). Summing rule: sum across base and DISTINCT hazard kinds; repeated hazards of one kind never add up (group by capability and kind, take the max count per kind). Sources list each kind once with all contributing hazard ids. Each CHOSE edge records why the capability was required ('base' or 'hazard:<id>:<kind>'). Unmet capabilities are stored on the Decision (unmet, unmet_reasons); a shortage never crashes a call.
- Hazard kinds are a closed vocabulary (HazardKind from seed/hazard_rules.csv); add_hazard refuses unknown kinds and lists the allowed ones.
- Trauma levels come from the CA EMSA Designated Trauma Centers list (updated 2025-08-25) and are stored as OFFERS {level}; they are displayed, never used to choose a hospital.
- Runtime labels are Incident, Decision, Caller, Address, Hazard. scripts/reset.py is the only reset path: dry run by default, --yes only for sjfd or sjfd_test, deletes runtime labels only and restores seed unit statuses.
- Tests write outputs to runs/ (gitignored); a full test run must leave git status clean.
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
  H -->|OFFERS level| C[Capability name]
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
  D[Decision decision_id ts agent rule_applied unmet unmet_reasons] -->|FOR| INC
  D -->|CONSIDERED capability eta_s rank| U
  D -->|CHOSE capability eta_s reason| U
  D -->|DESTINATION eta_s level| H
  D -->|SKIPPED reason eta_s| H
  D -->|ROUTE leg seq| I1
  D -->|RECALLED| HZ
  D -->|RECALLED| INC
  HZ -->|OF_KIND| HK[HazardKind name crew_note synthetic]
  HK -->|ADDS_REQUIREMENT incident_type count| C
```
ASSIGNED_TO (Unit to Incident) is an addition beyond the original spec, so clear() frees only units dispatched to that incident.

## Phase 1 pitfalls
- point() and distance() work on FalkorDB 4.22.1 (distance in meters, float32 precision).
- In osmnx 2.1.1 the SCC function is ox.truncate.largest_component(G, strongly=True).
- B2 SCC cut drops 103 nodes; CSV export also drops 42 parallel edges.
- OSM operator tags are stale: Regional shows HCA and O'Connor shows Verity Health, both are county-run now. Do not trust them.
- scripts/load.py reads hospital coordinates from data/processed/hospitals_raw.csv (gitignored), so run Phase 0B fetch_pois.py first on a fresh clone.
- Long multi-file shell heredocs failed once in this shell; write files with the editor tool.

## Phase 4B pitfalls
- mcp 2.x is not the 1.x API: use mcp.server.lowlevel.Server with on_list_tools/on_call_tool callbacks (FastMCP was renamed MCPServer); Tool fields are snake_case (input_schema, is_error).
- Nothing but protocol messages may go to stdout in the MCP server.
- Run `pip install -e .` once; scripts and probes then import graphdispatch from anywhere.
- Same-second incidents/hazards need an insertion-order tie-break (id()) or recall order is random.
- Bash heredocs containing quotes and fences fail intermittently in this shell; write files with the editor tool.

## Phase 3 pitfalls
- A graph is created as a side effect of select_graph + any query (phase0/probe_procs.py left an empty probe_procs graph).
- Hazards created before HazardKind existed have no OF_KIND edge and are ignored by effective_requirements.
- Seed hospitals.csv source text contains commas; the field is quoted.

## Phase 2 pitfalls
- ro_query works with CALL algo.SPpaths; use it for all reads.
- OPTIONAL MATCH + collect({...}) returns one all-null map when nothing matches; filter in Python. UNWIND over an empty list drops all rows, so skip empty writes.
- record_decision is several write queries (not one transaction); a crash mid-way can leave a partial decision.
- Test helper queries (wipe_runtime, set_unit_status) live in queries.cypher; drop_graph and wipe are guarded to *_test graphs only.
- Fresh clone: python scripts/load.py (with GRAPH_NAME set) needs only seed/ and a running FalkorDB.

## Pipeline (Phase 4B)
```mermaid
graph LR
  T[caller text] --> C[Bedrock forced classify_call]
  C --> V{validate against graph enums}
  V -- invalid --> R[IntakeRejected, nothing written]
  V -- valid --> I[create Incident + Address]
  I --> H[caller-reported Hazards]
  H --> E[effective_requirements]
  E --> RC[recommend: SPpaths ETAs]
  RC --> D[record_decision]
  D --> W[why explanation]
  W --> HU[human confirms dispatch]
```

## Claude Desktop MCP config (do not paste into the config automatically)
Add under `mcpServers` in `claude_desktop_config.json`; the venv python is launched by absolute path:
```json
{
  "mcpServers": {
    "graphdispatch": {
      "command": "[repo]\\.venv\\Scripts\\python.exe",
      "args": ["-m", "graphdispatch.mcp_server"],
      "env": { "GRAPH_NAME": "sjfd_test" }
    }
  }
}
```
FalkorDB must be running on localhost:6379. Use GRAPH_NAME sjfd for the real demo graph.

## QUERIES
Every named query in graphdispatch/queries.cypher (kept in sync by tests/test_docs.py):
- `idx_intersection`: Index Intersection.osm_id.
- `idx_unit`: Index Unit.unit_id.
- `idx_station`: Index Station.station_id.
- `idx_hospital`: Index Hospital.osm_id.
- `idx_capability`: Index Capability.name.
- `idx_incident_type`: Index IncidentType.name.
- `idx_incident`: Index Incident.incident_id.
- `idx_address`: Index Address.address_id.
- `idx_caller`: Index Caller.caller_id.
- `idx_hazard`: Index Hazard.hazard_id.
- `idx_decision`: Index Decision.decision_id.
- `load_intersections`: Batch-merge intersections with a geo point.
- `load_roads`: Batch-merge directed ROAD edges.
- `load_capabilities`: Merge capability vocabulary nodes.
- `load_stations`: Merge stations.
- `load_hospitals`: Merge hospitals (matched by osm_id, never by name).
- `load_offers`: Link hospitals to the capabilities they offer, with an optional designation level.
- `load_units`: Merge synthetic units and their base station.
- `load_unit_caps`: Link units to their capabilities.
- `load_incident_types`: Merge synthetic incident types.
- `load_requires`: Link incident types to required capabilities with counts.
- `load_dest_needs`: Link incident types to the destination capability, with optional bypass-rule properties (null props are skipped).
- `snap_station`: Snap a station to its nearest intersection and store snap_m.
- `snap_hospital`: Snap a hospital to its nearest intersection and store snap_m.
- `count_labels`: Node counts per label.
- `count_rels`: Relationship counts per type.
- `snap_report`: Snap distances for every station and hospital.
- `snap_incident`: Nearest intersection to an incident location and the snap distance in meters.
- `unit_candidates`: Multi-hop: required capabilities to available units, their station and station intersection.
- `required_caps`: Capabilities (with counts) an incident type requires, including those no available unit has.
- `dest_capability`: Destination capability and optional fallback rule for an incident type (no row if none).
- `hospitals`: Every hospital with its intersection, offered capabilities and designation levels.
- `eta`: Travel time in seconds along the cheapest outgoing path between two intersections via SPpaths.
- `route`: Cheapest outgoing path between two intersections via SPpaths: weight and ordered node ids.
- `create_incident`: Create a synthetic incident with its caller, address and nearest intersection (call_text and intake_model are set only for LLM intake).
- `incident_info`: Incident status, type and address.
- `recall_incidents`: Earlier incidents at the same address since a cutoff time.
- `recall_hazards`: Hazards at the incident's address that are valid at the given time, with the kind's crew note.
- `add_hazard`: Create a hazard of a known kind at an address (address created with label only if missing).
- `hazard_reported_in`: Link a hazard to the incident it was reported in.
- `decision_create`: Create a decision node for an incident, with unmet capabilities and their reasons.
- `decision_considered`: Record candidate units considered, with capability, ETA and rank.
- `decision_chose`: Record chosen units with the capability they cover, ETA and why the capability was required.
- `decision_destination`: Record the chosen destination hospital, ETA and designation level.
- `decision_skipped`: Record hospitals skipped, with reason and ETA.
- `decision_route`: Record route path nodes per leg in order.
- `decision_recalled_hazards`: Record hazards surfaced to this decision.
- `decision_recalled_incidents`: Record earlier incidents surfaced to this decision.
- `why`: Everything recorded for one decision, in a single query.
- `decision_units`: Units chosen by a decision with their current status.
- `dispatch`: All-or-nothing dispatch: assign the chosen units and mark the incident dispatched only if every chosen unit is available.
- `clear`: Return an incident's assigned units to available and mark the incident cleared.
- `set_unit_status`: Administrative/test helper: set one unit's status.
- `wipe_runtime`: Test helper: delete all runtime nodes (incidents, callers, addresses, hazards, decisions).
- `unit_statuses`: Every unit with its current status.
- `assigned_to_count`: Number of ASSIGNED_TO relationships (test helper).
- `idx_hazard_kind`: Index HazardKind.name.
- `load_hazard_kinds`: Merge synthetic hazard kinds with their crew notes.
- `load_hazard_adds`: Link hazard kinds to capabilities they add for an incident type.
- `hazard_kinds`: List allowed hazard kinds.
- `effective_requirements`: Incident type requirements plus requirements added by active hazards at the incident's address; hazards are grouped by (capability, kind) taking the max count per kind, so repeated hazards of one kind never double count.
- `runtime_label_counts`: Node counts for runtime labels only (reset dry run).
- `runtime_rel_counts`: Relationship counts for relationships touching runtime labels (reset dry run).
- `seed_label_counts`: Node counts for non-runtime (seed) labels.
- `seed_rel_counts`: Relationship counts for relationships between seed labels only.
- `incident_type_names`: List incident type names (enum source for LLM tools).
- `address_hazards`: Active hazards at an address (by normalized address_id) with crew notes.
- `address_incidents`: Incidents at an address (by normalized address_id) created since a cutoff time.
- `open_incidents`: Incidents that are open or dispatched, with their address.
- `unit_status_detail`: Every unit with type, status and station.

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