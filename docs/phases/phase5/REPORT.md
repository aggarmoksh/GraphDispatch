# Phase 5 Report: web app

Units, incidents and callers are SYNTHETIC. The page is served by FastAPI from graphdispatch/static/ (plain ES modules, no build step).

## Endpoints
| method and path | what it does | LLM |
|---|---|---|
| GET /api/health | real FalkorDB read (count Intersection); 503 with a plain message if it fails | no |
| GET /api/meta | graph name and counts, incident types, hazard kinds, 10 stations, 3 hospitals (lat, lon, capabilities, levels), 22 units | no |
| POST /api/call {text, lat, lon} | take_call through Bedrock; capped by LLM_DAILY_CAP (default 150, UTC date, runs/llm_daily.json) and 6 per 10 minutes per client IP; 429 over a cap | yes |
| POST /api/recommend {lat, lon, incident_type, address} | graph-only run_call | no |
| GET /api/decision/{id} | why() as JSON plus routes and queries | no |
| POST /api/dispatch/{decision_id} | human action; 409 if a unit is no longer available (nothing changes); 404 for an unknown decision | no |
| POST /api/clear/{incident_id} | human action | no |
| GET /api/incidents | open and dispatched incidents, active hazards with positions, unit statuses | no |
| POST /api/hazard {address, kind, note} | add a hazard (kind validated against the graph) | no |

Every decision response includes `routes` ([lon, lat] arrays per leg from the ROUTE edges) and `queries` (name, real Cypher text from queries.cypher, ms, summarized parameters) for each query that request ran. Caller ids are generated server-side.

## Tests: 56 passed, 0 failed (42 earlier plus 14 new in tests/test_api.py)
Health 200 and 503 (FALKORDB_PORT pointed at a closed port, then restored); meta (10 stations, 3 hospitals, 22 units, levels, no secrets); recommend returns routes in [lon, lat] inside the box and real Cypher for 8 named queries; input validation (unknown type, out of area, bad coordinates); decision GET and 404; dispatch, 409 on a second dispatch, clear, 404s; hazard endpoint changes the next decision (HM26 with reason, crew note); /api/call with a canned model (no confidence in the response); rejected model output gives 422 and writes nothing; LLM_DAILY_CAP=0 gives 429 on /api/call while /api/recommend still works; per-IP limit (6 pass, the 7th is 429); daily counter persists by UTC date; static page, the header sentence and vendored assets are served, no secrets in static files; /api/recommend latency.

Bedrock calls during pytest: zero. runs/llm_calls.log: 19 lines before pytest, 19 after (the 19 includes the operator's own earlier runs).

## Latency
/api/recommend over 20 requests (TestClient, includes routes and the full query recording): p50 46.8 ms, p95 49.3 ms (limit 300 ms).

## Live smoke test (one Bedrock call, on sjfd_test)
POST /api/call with the L1 text: HTTP 200 in 2.24 s. Classified structure_fire with oxygen_storage reported, address 200 Demo Street; units T1, E8, T8 and HM26 ("added by oxygen_storage"); 35 recorded queries, routes for E8, HM26, T1, T8; the response has no confidence value. The daily counter read 1. Bedrock calls in this phase: 1 (limit 2). Total log lines afterwards: 20.

## Visual check (Playwright 1.64.0, chromium headless, graph-only, sjfd_test), docs/phases/phase5/screens/
| file | shows |
|---|---|
| 02-stroke-desktop.png | 1440x900, "Stroke, west side" (S1): 10 red station squares, 3 blue H hospitals, two red unit routes from station 7 to the incident ring, a blue hospital route to Regional (551 s), the stroke rule text, skipped hospitals, legend |
| 03-why-drawer-desktop.png | the Why drawer open on the `eta` query after selecting an ETA cell: the real Cypher with algo.SPpaths, 12 runs with parameters and ms, and the list of all 32 queries with timings |
| 04-oxygen-call1-desktop.png | oxygen preset, call 2 of the history (structure fire): HM26 "added by oxygen_storage", a long red route from station 26, the yellow outlined hazard diamond beside the incident ring, memory of the address with the crew note |
| 05-oxygen-call2-desktop.png | the following cardiac arrest call at the same address: O'Connor chosen, blue hospital route, the hazard and the earlier incident recalled |
| 06-stroke-mobile.png | 390x844: map on top, key at top left, call box below |
| 07-stroke-mobile-full.png | 390x844 full page: map, call box, decision panel, Why bar and footer stacked; no horizontal scroll |

- Console errors: 0 (and 0 page errors) across both viewports.
- Horizontal scroll: none (scrollWidth equals innerWidth at 1440 and at 390).
- Network hosts at runtime: localhost, tiles.openfreemap.org, fonts.googleapis.com, fonts.gstatic.com only. No failed requests in the final run.
- Screenshots total about 0.7 MB (palette-compressed).

## MapLibre and tiles
- MapLibre GL JS 5.24.0 vendored in graphdispatch/static/vendor/ from https://cdn.jsdelivr.net/npm/maplibre-gl@5.24.0/dist/maplibre-gl.js (and .css, LICENSE.txt); the file header confirms 5.24.0. Recorded in seed/DATA.md.
- Style https://tiles.openfreemap.org/styles/positron loaded (HTTP 200 and rendered in the browser); the raster fallback was not needed. Attribution for OpenStreetMap contributors and OpenFreeMap is on the map and in the footer.

## Files created or changed
New: graphdispatch/api.py, graphdispatch/static/{index.html, style.css, app.js, api.js, map.js, panel.js, vendor/maplibre-gl.js, vendor/maplibre-gl.css, vendor/LICENSE.txt}, tests/test_api.py, docs/phases/phase5/screenshots.py, docs/phases/phase5/screens/*.png and check.json, docs/phases/phase5/REPORT.md. Changed: graphdispatch/db.py (query recorder, reset_connection), ops.py (add_hazard position), queries.cypher (health, meta, map and route coordinate queries), pyproject.toml, requirements.txt, AGENT.md, seed/DATA.md, POSTLAUNCH.md, AI_DISCLOSURE.md, FRICTION_LOG.md.

## Flags
- The graph-only oxygen preset deviates from the written order (see AGENT.md): the hazard is recorded first, then structure_fire, then cardiac_arrest. The written order cannot satisfy the acceptance (HM26 with its reason) because oxygen_storage only adds hazmat to structure_fire.
- Hospital and station markers are drawn at the snapped road intersection (up to about 150 m from the true building position).
- Hazard markers are offset 20 px so they are not hidden under the incident ring.
- The operator's earlier rerun of docs/phases/phase4a/probe_intake.py left docs/phases/phase4a/intake_results.csv modified in the working tree; it is not in this commit.
- The per-IP limiter is in memory per process, so it resets on restart and is per worker.
- Two calls to the same preset in one session reuse the same address, so later calls recall earlier ones (this is the memory feature working).
- The server I started for the visual check was stopped afterwards; it was on sjfd_test only.

## Not done
No auth, voice, multilingual, mutual aid, closures, deployment, Next.js or JS build step. No git remote or push. No reset --yes on sjfd. No seed data changed. No secrets in static files or responses. Planning files untouched. At most 1 Bedrock call (the smoke test).
