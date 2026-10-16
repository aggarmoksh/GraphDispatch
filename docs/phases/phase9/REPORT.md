# Phase 9 Report: road closures

Closures are modeled by retyping `ROAD` to `CLOSED_ROAD`, so `algo.SPpaths` with `relTypes ['ROAD']` skips them and no new algorithm is needed. Everything is synthetic. No deploy, no Bedrock call (the call log stayed at 50 lines), no change to eval/PROTOCOL.md, eval/scenarios.json, eval/oracle.py or eval/RESULTS.md (checked with git).

## 0. Probe (graph sjfd_test; `docs/phases/phase9/probe.py`, full output in `docs/phases/phase9/probe_output.txt`): PASSED
S1's hospital route has 46 intersections; the probe closed its middle edge (33783786 to 311645239, Bayshore Freeway) with the exact close and reopen queries below.
```
before closure  relTypes ['ROAD']:               weight 550.50 s, uses 33783786->311645239: True
edge counts before: {'ROAD': 10430, 'CLOSED_ROAD': 0}
close_road returned: [['clo-probe']] | edge counts after: {'ROAD': 10429, 'CLOSED_ROAD': 1}
CLOSED_ROAD edges: [[33783786, 311645239, 21.09, 612.82, 'Bayshore Freeway', 'clo-probe']]
after closure   relTypes ['ROAD']:               weight 584.87 s, uses closed pair: False, types ['ROAD']
after closure   relTypes ['ROAD','CLOSED_ROAD']: weight 550.50 s, uses closed pair: True, types ['CLOSED_ROAD', 'ROAD']
reopen_road returned: [['clo-probe']] | edge counts: {'ROAD': 10430, 'CLOSED_ROAD': 0} | restored props equal: True | weight back to 550.50 s
RESULT: ['ROAD'] skips the closed road: True; ['ROAD','CLOSED_ROAD'] still traverses it: True; reopen restores exactly: True
```

## 1. close_road and reopen_road (graphdispatch/queries.cypher; each is one query)
`close_road` (params: src, dst, closure_id, reason, now, expires):
```cypher
MATCH (a:Intersection {osm_id: $src}), (b:Intersection {osm_id: $dst}) OPTIONAL MATCH (a)-[f:ROAD]->(b) OPTIONAL MATCH (b)-[r:ROAD]->(a) WITH a, b, f, r WHERE f IS NOT NULL OR r IS NOT NULL CREATE (c:Closure {closure_id: $closure_id, reason: $reason, closed_at: $now, expires_at: $expires, src_osm: $src, dst_osm: $dst, name: coalesce(f.name, r.name, ''), synthetic: true}) CREATE (c)-[:AT]->(a), (c)-[:AT]->(b) FOREACH (e IN CASE WHEN f IS NULL THEN [] ELSE [f] END | CREATE (a)-[:CLOSED_ROAD {travel_s: e.travel_s, length_m: e.length_m, name: e.name, closure_id: $closure_id}]->(b)) FOREACH (e IN CASE WHEN r IS NULL THEN [] ELSE [r] END | CREATE (b)-[:CLOSED_ROAD {travel_s: e.travel_s, length_m: e.length_m, name: e.name, closure_id: $closure_id}]->(a)) FOREACH (e IN CASE WHEN f IS NULL THEN [] ELSE [f] END | DELETE e) FOREACH (e IN CASE WHEN r IS NULL THEN [] ELSE [r] END | DELETE e) RETURN c.closure_id AS id
```
`reopen_road` (params: closure_id, now):
```cypher
MATCH (c:Closure {closure_id: $closure_id}) WHERE c.reopened_at IS NULL MATCH (a:Intersection {osm_id: c.src_osm}), (b:Intersection {osm_id: c.dst_osm}) OPTIONAL MATCH (a)-[f:CLOSED_ROAD {closure_id: $closure_id}]->(b) OPTIONAL MATCH (b)-[r:CLOSED_ROAD {closure_id: $closure_id}]->(a) FOREACH (e IN CASE WHEN f IS NULL THEN [] ELSE [f] END | CREATE (a)-[:ROAD {travel_s: e.travel_s, length_m: e.length_m, name: e.name}]->(b)) FOREACH (e IN CASE WHEN r IS NULL THEN [] ELSE [r] END | CREATE (b)-[:ROAD {travel_s: e.travel_s, length_m: e.length_m, name: e.name}]->(a)) FOREACH (e IN CASE WHEN f IS NULL THEN [] ELSE [f] END | DELETE e) FOREACH (e IN CASE WHEN r IS NULL THEN [] ELSE [r] END | DELETE e) SET c.reopened_at = $now RETURN c.closure_id AS id
```
The Closure node is kept after reopening (reopened_at set) so earlier decisions stay explainable. `closures_list`, `active_closure_count`, `expired_closures`, `nearest_road_segment`, `eta_all`, `route_all`, `decision_rerouted` and `idx_closure` were added (85 queries now; QUERIES.md regenerated). Changed: `load_roads` skips pairs that are currently closed (the loader runs on every app start), `decision_create` and `why` carry `changes`, `no_route` and the REROUTED_AROUND rows, and the runtime reset and count queries treat Closure and CLOSED_ROAD as runtime data.

## 2. Provenance
When any closure is active, `recommend()` also computes each chosen leg over `['ROAD','CLOSED_ROAD']`. If that path uses a closed road and the real path is longer, the decision gets `(:Decision)-[:REROUTED_AROUND {leg, extra_s}]->(:Closure)`. `Decision.changes` records the unit (per capability) or hospital that would have been chosen without the closures, and `Decision.no_route` lists legs that became unreachable ("No route: hospital" in the panel); a decision never crashes on an unreachable leg. `why()` returns all of it, still as one query. With no closure active the result is identical to before (the 86 earlier tests are the evidence).

## 3. API and public-site limits
`GET /api/closures` (active closures with geometry), `POST /api/closures` with `{lat, lon, reason}` (snaps to the nearest open ROAD segment by midpoint distance) or `{src_osm, dst_osm}`, `DELETE /api/closures/{id}`. At most 3 active closures (409 with a clear message beyond that), expiry after DEMO_EXPIRE_MIN through the existing sweeper (tested with a stale closure at app startup), at most 10 close actions per client IP per 10 minutes (429; same client-IP rules as the AI cap). Both are tested.

## 4. The demo closure and its effect (seed/demo_closures.csv, chosen with the independent oracle, graph only)
No single closure on S1's routes both makes a chosen leg detour and changes the chosen unit or hospital: the best detour (Bayshore Freeway on the hospital leg) changes nothing else, and the best unit-changer (West Taylor Street) routes no chosen leg around itself because other stations take over. So the file has **two rows** and the preset closes both (checked together with the oracle: everything stays reachable). This is a deviation from "pick the one closure"; it is flagged in the friction log.

| S1, graph only | before (no closures) | after (both demo closures) |
|---|---|---|
| Paramedic unit (ALS) | E7, 132.3 s (2:12) | E10, 156.7 s (2:37) |
| Ambulance (transport) | M7, 132.3 s (2:12) | M10, 156.7 s (2:37) |
| Hospital | Regional, 550.5 s (9:11) | Regional, 634.3 s (10:34) |
| Recorded | none | REROUTED_AROUND hospital leg around Bayshore Freeway, +83.8 s (+1:24); changes: ALS E7 to E10, transport M7 to M10 |

Reopening both restores E7 and M7 at 132.3 s and Regional at 550.5 s exactly (`docs/phases/phase9/before_after.py`).

## 5. UI
Closed segments are dashed dark lines with a small "closed" label; a "Close a road" toggle (the next map click closes the nearest road); a "Closed roads" list with Reopen buttons and a "reopens by itself in m:ss" countdown; a legend entry; the preset "Road closed on the stroke route". The decision panel shows "Rerouted around Bayshore Freeway (synthetic closure): +1:24", "Without the closure, E7 would have gone (Paramedic (ALS))" and the same for the transport unit; these lines open the Why drawer on `route_all` (the comparison path, which really contains CLOSED_ROAD) and `close_road` (the Cypher, with the real recorded run when the page closed the road).

## 6. Tests: 102 passed, 0 failed (86 earlier plus 16 in tests/test_closures.py)
Close and reopen round trip restores exact edge counts, sums and properties; routes never contain a closed pair; the decision links REROUTED_AROUND with extra_s greater than 0 (equal to the ETA difference within 0.2 s); a changed unit is recorded and explained; both closures together reroute and change units; an unreachable leg is reported (not a crash) in the decision and through the API; expired closures reopen, also at app startup; the loader does not undo a closure; API close by point and by pair, list, reopen, 404, 409 and validation; the cap of 3; the limit of 10 per IP; meta carries the demo closures; QUERIES.md sync. Bedrock calls in pytest: zero (call log 50 before and after).

## 7. Visual check (Playwright on sjfd_test, graph only), docs/phases/phase9/screens/
| file | shows |
|---|---|
| 01-closure-desktop.png | 1440x900, the preset: two "closed" labels, units E10 and M10, hospital 10:34, the rerouted and "Without the closure" lines, red and blue routes, everything inside the view |
| 02-why-drawer-closure-desktop.png | the Why drawer opened from the "Rerouted around" line, on `route_all` with its Cypher over ROAD and CLOSED_ROAD |
| 03-close-a-road-click-desktop.png | "Close a road" then a map click: a third closure in the list |
| 04-closure-mobile.png | 390x844, the same preset, map on top |
| 05-closure-mobile-full.png | 390x844 full page |
Console errors: 0 (page errors 0); no horizontal scroll at 1440 or 390; only the tile server, fonts and localhost were contacted; both closure labels inside the map and clear of the legend; the Reopen button works.

## 8. Flags
- Two demo-closure rows instead of one (section 4).
- README: one number changed (75 to 85 named queries) because an existing test checks it; no other README or docs change (docs beyond QUERIES.md regeneration were out of scope).
- The public copy (graphdispatch-public) was not rebuilt; it needs rebuilding from this commit, and README, QUERIES.md and the new files will then appear there.
- The live site is not updated (no deploy); closures there start when the operator ships.
- The decision comparison runs extra shortest-path queries only while a closure is active (about 10 more per call); `run_call` p95 in the latency test was 62 ms.
- The timing table in QUERIES.md measures the `why` query with extra rows left by earlier timed writes on the same decision (51 ms in the table); the real `why` p95 in the test suite is 10 ms.
- The earlier dispatch rule still applies: nothing here dispatches or clears anything.

## 9. Not done
No v2 evaluation (rejected by the advisor), no MCP tool change, no deploy or ship.sh, no HTTPS, mutual aid or docs beyond QUERIES.md regeneration. No git remote or push, no AWS change, no Bedrock call, no reset on sjfd. Planning files and the four protected eval files untouched.
