# Phase 4B Report

Caller texts, units, incidents and hazards are SYNTHETIC. The LLM never writes Cypher: it only fills enums built from the graph, and its output is validated in code before anything is written.

## Tests: 42 passed, 0 failed (previous 30 plus 12 new), stable over 3 consecutive runs
| group | tests | result |
|---|---|---|
| Phases 1 to 4A (recommend, memory, provenance, rules, hazard rules, docs) | 30 | pass |
| H7 two active oxygen_storage hazards: hazmat need 1, HM26 chosen, no UNMET, reason names oxygen_storage once, "oxygen_storage x2: ..." grouped, one crew note | 1 | pass |
| Address normalization ("200 Demo Street", "200 demo st.", " 200  DEMO St " give one id; device labels untouched) | 1 | pass |
| I1 caller-reported hazard counts in the same call (HM26 chosen, Hazard.reported_by = caller, never dispatched, no confidence in output) | 1 | pass |
| I2 second call recalls the hazard and the I1 incident, prints the crew note | 1 | pass |
| I3 invalid model output rejected, nothing written (alien_attack; hazard "unicorns"; wrong tool name) | 3 | pass |
| I4 no address gives "device@37.3360,-121.8900"; model address used when no override; call_text and intake_model stored | 3 | pass |
| M1 MCP over stdio: exactly 6 tools, S1 gives Regional, alien_attack and out-of-area return errors without crashing, unknown tool "dispatch" is an error, server still answers afterwards | 1 | pass |
| only report_hazard writes | 1 | pass |

Bedrock calls during pytest: zero. LLM_CALL_CAP=0 is set in the test environment, llm.converse is monkeypatched with canned responses (which also assert the tool enums equal the graph's), and a session-end check asserts llm.call_count() == 0.

Call log (runs/llm_calls.log) line counts around pytest: 15 before, 15 after; and 17 before, 17 after the final run (the 2 extra lines are the live run L1 and L2).

## effective_requirements (still one query)
```
MATCH (inc:Incident {incident_id: $incident_id})-[:OF_TYPE]->(t:IncidentType) OPTIONAL MATCH (t)-[q:REQUIRES]->(c1:Capability) WITH inc, t, collect({cap: c1.name, need: q.count, source: 'base'}) AS base OPTIONAL MATCH (inc)-[:AT]->(:Address)<-[:AT]-(h:Hazard)-[:OF_KIND]->(k:HazardKind)-[r:ADDS_REQUIREMENT]->(c2:Capability) WHERE h.valid_from <= $now AND $now <= h.valid_to AND r.incident_type = t.name WITH base, c2.name AS cap, k.name AS kind, max(r.count) AS need, collect(h.hazard_id) AS ids WITH base, collect({cap: cap, need: need, source: 'hazard:' + reduce(acc = '', i IN ids | CASE WHEN acc = '' THEN i ELSE acc + ',' + i END) + ':' + kind}) AS added UNWIND base + added AS x WITH x WHERE x.cap IS NOT NULL RETURN x.cap AS cap, sum(x.need) AS need, collect(x.source) AS sources ORDER BY cap
```
Rule: sum across base and DISTINCT hazard kinds; repeated hazards of one kind use the max count for that kind. Each kind appears once in sources with all contributing hazard ids.

## Live run on sjfd_test (after reset --yes on sjfd_test), 2 Bedrock calls
Model us.anthropic.claude-haiku-4-5-20251001-v1:0, us-east-1.

L1 (caller-201): "Smoke coming out of the garage at 200 Demo Street, my neighbor uses home oxygen, please hurry"
```
Classified as structure_fire; hazards reported by caller: oxygen_storage; address used: 200 Demo Street
Model note: Smoke from garage with oxygen storage on premises creates fire and explosion hazard
Decision dec-1780f0454d (deterministic-v1) for incident inc-0f8281a1fd [structure_fire, synthetic] at 200 Demo Street, status open
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
Recalled hazard: oxygen_storage: reported by caller
  Crew note: Stored oxygen accelerates fire; no open flame
take_call 1980 ms (LLM 1910 ms). Not dispatched.
```
L2 (caller-202): "My neighbor at 200 Demo St just collapsed and isn't breathing"
```
Classified as cardiac_arrest; hazards reported by caller: none; address used: 200 Demo St
Model note: Caller reports neighbor collapsed and not breathing, indicating cardiac arrest
Decision dec-a9685ecbd8 (deterministic-v1) for incident inc-65bff4019c [cardiac_arrest, synthetic] at 200 Demo Street, status open
Rule: fastest hospital offering emergency: O'Connor Hospital (352 s)
Chosen units (synthetic):
  E8    covers als               ETA 134 s  [required by incident type]
  M3    covers transport         ETA 150 s  [required by incident type]
  considered for als: E8 134s, E30 140s, E3 150s, M3 150s, E7 196s
  considered for transport: M3 150s, M7 196s, M5 315s, M26 429s, M10 433s
Destination: O'Connor Hospital (ETA 352 s)
Route legs (intersections): E8=17, M3=27, hospital=48
Recalled hazard: oxygen_storage: reported by caller
  Crew note: Stored oxygen accelerates fire; no open flame
Recalled earlier incident: inc-0f8281a1fd (structure_fire)
take_call 1705 ms (LLM 1639 ms). Not dispatched.
```
- L1: structure_fire, HM26 added by the caller-reported oxygen_storage, no UNMET. L2: cardiac_arrest, the oxygen hazard recalled once with its crew note, plus the L1 incident. "200 Demo Street" and "200 Demo St" resolved to the same Address.
- take_call latency: 1,980 ms and 1,705 ms, p50 about 1.84 s (limit 2.5 s). The LLM call is about 95% of it.
- Bedrock calls in this phase: 2 (limit 4).

## MCP server
- SDK: package `mcp`, version 2.3.0 (recorded in requirements.txt; jsonschema 4.26.0 used for argument validation). Python 3.12.4. The 2.x API differs from 1.x (FastMCP renamed MCPServer); the server uses mcp.server.lowlevel.Server with explicit schemas.
- Launch: python -m graphdispatch.mcp_server (stdio). Claude Desktop config snippet is in AGENT.md; no Claude Desktop config was touched.
- Exactly 6 tools (schemas are additionalProperties:false; enums are read from the graph when the tool list is built):

| tool | writes | arguments |
|---|---|---|
| recommend_units | no | lat, lon (numbers), incident_type (enum: 7 graph types) |
| recall_address | no | address_label (string, 1 to 200 chars) |
| explain_decision | no | decision_id (string, 1 to 64 chars) |
| list_open_incidents | no | none |
| unit_status | no | none |
| report_hazard | yes (only one) | address_label, kind (enum: graph HazardKind names), note (1 to 200 chars) |

- No dispatch tool, no clear tool, no tool name or property containing cypher/query/statement; every string property is an enum or length-bounded. Errors (bad enum, out of area, unknown tool) come back as isError results and the server keeps running.

## Packaging and import check
pyproject.toml added; pip install -e . done in the venv. From C:\Users (outside the repo):
`python -c "import graphdispatch, sys; print(graphdispatch.__file__)"` printed `[repo]\graphdispatch\__init__.py`.
`python docs/phases/phase4a/probe_intake.py --help` from the repo root prints usage and makes no Bedrock call (it now needs `--run` to call the model; log stayed at 15 lines).

## Files created or changed
New: pyproject.toml, graphdispatch/{intake.py, take_call.py, tools.py, mcp_server.py}, seed/address_suffixes.csv, tests/{test_intake.py, test_mcp.py}, docs/phases/phase4b/REPORT.md. Changed: graphdispatch/{ops.py, queries.cypher}, docs/phases/phase4a/probe_intake.py (argparse guard), tests/{conftest.py, test_hazard_rules.py}, AGENT.md (pipeline diagram, summing rule, MCP config, QUERIES), requirements.txt, .gitignore (*.egg-info), FRICTION_LOG.md, POSTLAUNCH.md, AI_DISCLOSURE.md.

## Flags
- The operator re-ran docs/phases/phase4a/probe_intake.py at 07:31 UTC (6 Bedrock calls; call log went from 9 to 15 lines before this phase started). It overwrote the working-tree docs/phases/phase4a/intake_results.csv with identical classifications and different latencies. I left that file out of this commit so the advisor-verified 4A version stays in git.
- id(node) is not monotonic after deletes in FalkorDB, so same-second ordering uses a new created_ns property (Incident and Hazard). Legacy sjfd nodes have no created_ns.
- A call's own caller-reported hazard prints as "Recalled hazard" in the same call (L1). It is correct for crew safety but the label is misleading; POSTLAUNCH.
- The model's "reason" text is shown labeled "Model note"; it is LLM text and not used for any decision.
- The stored call_text is synthetic caller text; do not use real caller data.
- sjfd was not written in this phase (live run and tests use sjfd_test); the operator's existing sjfd hazards remain without OF_KIND/created_ns.

## Not done
No FastAPI, frontend, free-form chat agent, mutual aid, closures or deployment. No new model. No git remote or push. No AWS changes. No reset --yes on sjfd. Claude Desktop config untouched. No change to unit, capability, road or hazard rule seed data. Planning files untouched.
