# GraphDispatch

Dispatch decision support for emergency calls: every recommendation is a walk through a FalkorDB graph of San Jose roads, stations, hospitals and what the system remembers about an address. Built for Graph Hacks (WeMakeDevs x FalkorDB).

**This is a hackathon prototype on synthetic data, not a real dispatch system.**

## What the graph decides

- **Which units to send, and how fast they get there.** Road travel time is computed inside FalkorDB with `algo.SPpaths` over a directed road graph. The units required for an incident, including units added because of a remembered hazard at the address, come from one query, `effective_requirements`.
- **Which hospital to take the patient to.** The nearest hospital is often the wrong one, because the needed capability (trauma, burn, clot removal for a stroke) differs by hospital. For strokes, the AHA bypass limits are stored on a graph edge and applied to the real road times; the nearest hospital that was skipped is shown with its reason.
- **What to remember.** Hazards and earlier incidents at an address change later decisions, and every decision is stored as nodes and edges (units considered, chosen, hospitals skipped, route, memory recalled), so "why?" is answered by one Cypher query.

## Live demo

**http://3.220.38.68** (synthetic data, plain HTTP, so do not type anything real). Use **Graph only** to run with no AI, or the AI mode for caller text; the AI mode is capped per day and per visitor.

![Stroke on the west side: the nearest hospital, O'Connor, is skipped for lack of clot removal, so the patient goes to Regional; unit routes in red, hospital route in blue](docs/img/s1-desktop.png)

*Stroke, west side. O'Connor is nearest but cannot remove clots; Regional is 8:22 farther, inside the AHA 30:00 limit, so the patient goes to Regional. Every line in the decision panel opens the Cypher query that produced it.*

![A collapse next door at an address where oxygen storage was reported earlier: the system remembers the hazard and the earlier fire](docs/img/oxygen-call2-desktop.png)

*A second call at the same address. The oxygen hazard and the earlier fire are recalled from the graph.*

## Why a graph

The hackathon asks whether the product still works once FalkorDB is taken out. We tested that with a pre-registered protocol ([eval/PROTOCOL.md](eval/PROTOCOL.md)) and an independent oracle (`eval/oracle.py`, which recomputes every answer from the seed CSVs with its own Dijkstra and imports nothing from the app). 24 scenarios, three configurations, scored against the oracle; full results in [eval/RESULTS.md](eval/RESULTS.md).

- **A**: GraphDispatch (the graph does the routing, rules and memory).
- **B**: no graph, no LLM: nearest by straight-line distance, same assignment rules.
- **C**: Claude Haiku 4.5 given every fact as text (stations, units, hospitals, rules, hazards, earlier incidents) but no road network.

| | A GraphDispatch | B straight-line | C LLM with facts as text |
|---|---|---|---|
| Exact unit set (of 24) | 24 | 19 | 10 |
| Every required capability covered (of 24) | 24 | 23 | 24 |
| Hazard-added unit included (O1) | 1 of 1 | 0 of 1 | 1 of 1 |
| Correct hospital (of 16) | 16 | 16 | 14 |
| Stroke rule applied correctly (of 4) | 4 | 4 | 4 |
| Memory recall (O2) | 1 of 1 | 0 of 1 | 1 of 1 |
| Latency, median / p95 (ms) | 38.1 / 48.3 | 0.0 / 0.1 | 1274.3 / 1585.0 |
| Seconds lost vs the oracle, total (post hoc) | 0 | 195 | 2190 |
| Seconds lost, median / max in one scenario (post hoc) | 0.0 / 0 | 0.0 / 103 | 20.9 / 325 |

What this shows, and what it does not:

- Road travel time is what separates A from B on unit choice: the nearest station in a straight line is not always the fastest by road.
- Hospital choice did **not** differ: B picked the same hospital as the oracle in all 16 cases, because the three hospitals are ordered the same way by straight line and by road. This set does not show a hospital-choice benefit from the graph, and the four stroke scenarios did not discriminate either.
- The LLM baseline was **handed the memory** (the active hazard and the earlier incident, as text) and used it correctly. The graph's advantage on memory is that it stores, queries and applies it deterministically, not that a model cannot use the facts when it is given them. B has no memory by definition, so its zeros there are by construction.
- C had no road network by design; its failures measure what coordinates in text can support, not what a model with a routing tool could do.
- 24 synthetic scenarios in one small area, one run at temperature 0, 24 Bedrock calls: a demonstration, not a statistical study. The oracle is independent in code and method but shares its rules with the app, so it does not test whether the rules are medically right. The seconds-lost columns were added after the results and are labeled that way in [eval/RESULTS.md](eval/RESULTS.md). Cost of the AI baseline was not verified (tokens only are reported there).

## Graph model

Seed data (loaded by `scripts/load.py` from `seed/`): 4,268 nodes and 10,538 relationships (counts in [docs/seed_counts.json](docs/seed_counts.json)). Runtime data (incidents, decisions and so on) is created as calls come in.

```mermaid
graph LR
  I1["Intersection<br/>osm_id, lat, lon, loc"] -->|"ROAD travel_s, length_m, name"| I2["Intersection"]
  S["Station"] -->|"LOCATED_AT snap_m"| I1
  H["Hospital"] -->|"LOCATED_AT snap_m"| I1
  H -->|"OFFERS level"| C["Capability"]
  U["Unit (synthetic)"] -->|BASED_AT| S
  U -->|HAS_CAPABILITY| C
  T["IncidentType (synthetic)"] -->|"REQUIRES count"| C
  T -->|"DESTINATION_NEEDS fallback, max_extra_s, max_total_s"| C
  HK["HazardKind"] -->|"ADDS_REQUIREMENT incident_type, count"| C
  INC["Incident"] -->|OF_TYPE| T
  INC -->|AT| AD["Address"]
  INC -->|NEAREST| I1
  CL["Caller"] -->|CALLED_ABOUT| INC
  HZ["Hazard"] -->|AT| AD
  HZ -->|OF_KIND| HK
  HZ -->|REPORTED_IN| INC
  U -->|ASSIGNED_TO| INC
  D["Decision"] -->|FOR| INC
  D -->|"CONSIDERED / CHOSE"| U
  D -->|"DESTINATION / SKIPPED"| H
  D -->|"ROUTE leg, seq"| I1
  D -->|RECALLED| HZ
  D -->|RECALLED| INC
```

| Seed node label | Count | Seed relationship | Count |
|---|---|---|---|
| Intersection | 4,213 | ROAD | 10,430 |
| Unit | 22 | HAS_CAPABILITY | 43 |
| Capability | 11 | BASED_AT | 22 |
| Station | 10 | REQUIRES | 14 |
| Hospital | 3 | LOCATED_AT | 13 |
| IncidentType | 7 | OFFERS | 10 |
| HazardKind | 2 | DESTINATION_NEEDS | 5 |
| | | ADDS_REQUIREMENT | 1 |

## Cypher queries

The product depends on 75 named, parameterized queries in [graphdispatch/queries.cypher](graphdispatch/queries.cypher), all documented with their Cypher, callers, read or write, and timings in **[QUERIES.md](QUERIES.md)** (including `GRAPH.EXPLAIN` and `GRAPH.PROFILE`). The ones to read first:

- `unit_candidates`: available units with the needed capabilities, their station and the station's road intersection (a multi-hop traversal).
- `eta` and `route`: travel time and the ordered path between two intersections with `algo.SPpaths` on `travel_s`.
- `effective_requirements`: the incident type's requirements plus requirements added by active hazards at the address, counted once per hazard kind, in one query.
- `dest_capability` and `hospitals`: which capability the hospital must offer, the stroke bypass limits, and what each hospital offers.
- `recall_hazards` and `recall_incidents`: address memory.
- `why`: everything recorded for one decision, read back in a single query.
- `dispatch`: assigns the chosen units only if every one is still available, all or nothing, in one query.

## Architecture

```mermaid
graph TD
  B["Browser: MapLibre page"] --> API["FastAPI app"]
  MCP["MCP server (stdio): 6 tools, one write"] --> FN["Graph functions: recommend, memory, provenance, dispatch"]
  API --> FN
  API -->|"caller text, AI mode only, capped"| BR["Amazon Bedrock: Claude Haiku 4.5 intake<br/>forced tool, fills graph enums only, never writes Cypher"]
  BR --> API
  FN -->|"named parameterized Cypher"| DB[("FalkorDB")]
  ROLE["EC2 instance role: no keys on the host"] -.-> BR
```

The model never writes Cypher. It only fills values from lists that come from the graph (incident types, hazard kinds), and the output is validated in code before anything is written. Dispatch is never done by the model: it is a button a human presses.

## Setup

Local, with Docker (graph-only mode needs no AWS account):

```bash
git clone <this repository> graphdispatch && cd graphdispatch
cp .env.server.example .env.server        # keep LLM_DAILY_CAP=0 for graph-only; the file is gitignored
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
# open http://localhost:8080
docker compose -f docker-compose.yml -f docker-compose.local.yml down -v
```

The app loads the seed into FalkorDB by itself on start. For the AI mode locally, raise `LLM_DAILY_CAP` and add your own AWS credentials to `.env.server` (never commit them); on the deployed host the instance role is used instead.

Tests (Python 3.12, FalkorDB on port 6379; they use a separate graph `sjfd_test` and make no Bedrock calls):

```bash
docker run -d -p 6379:6379 falkordb/falkordb
python -m venv .venv && . .venv/bin/activate      # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q
```

MCP server (stdio; six tools, only `report_hazard` writes; there is no dispatch tool and no tool that takes Cypher). Claude Desktop config:

```json
{
  "mcpServers": {
    "graphdispatch": {
      "command": "<path-to>/graphdispatch/.venv/bin/python",
      "args": ["-m", "graphdispatch.mcp_server"],
      "env": { "GRAPH_NAME": "sjfd" }
    }
  }
}
```

On Windows use `<path-to>\graphdispatch\.venv\Scripts\python.exe`. Run the app without Docker: `python -m uvicorn graphdispatch.api:app --port 8000`.

## Deployment

One EC2 t3.micro running docker compose, plain HTTP, Bedrock reached through an instance role with a least-privilege policy. The operator checklist is in **[deploy/RUNBOOK.md](deploy/RUNBOOK.md)** and the policy in `deploy/iam-bedrock-policy.json`.

## Data sources and licenses

- Roads: © OpenStreetMap contributors, ODbL (https://www.openstreetmap.org/copyright); snapshot dated in [seed/DATA.md](seed/DATA.md).
- Map tiles: OpenFreeMap (https://openfreemap.org); map rendering: MapLibre GL JS, BSD-3-Clause (https://maplibre.org).
- Trauma designations: California EMSA "Designated Trauma Centers" list, updated 2025-08-25.
- Stroke destination rule: AHA Mission: Lifeline Stroke EMS triage algorithm (meded.stroke.org). Stroke center designations: strokeinfo.org. Hospital capabilities: scvmc.scvh.org trauma and burn pages and an EMS1 article of 2025-05-03 (see the per-row sources in `seed/hospitals.csv`).
- **Synthetic:** units, incident types, callers, addresses, hazards and incidents. No real calls, people or phone numbers are used. Hazard rules are invented for the demo. Details in [seed/DATA.md](seed/DATA.md).

## Limitations

- Not a real dispatch system and not for real emergencies. Units and incidents are synthetic.
- The AHA stroke numbers (30:00 extra, 45:00 total) are suburban figures applied to an urban area; the urban guidance gives none.
- The rule numbers shown in the panel are parsed from the sentence the rule code writes, not stored as numbers.
- The per-visitor rate limiter is in memory in one worker and resets on restart; the daily AI cap is persisted and is the real cost guard.
- The deployed copy is plain HTTP.
- The evaluation is 24 synthetic scenarios (see above).

## AI assistance

Claude Code (Anthropic) wrote the code from phase briefs written by the author. The author made the design decisions, ran the field checks and verified the results, and chose which claims to make. The in-product AI (Claude Haiku 4.5 on Amazon Bedrock) only classifies caller text into values the graph allows. See [AI_DISCLOSURE.md](AI_DISCLOSURE.md).

## Friction log

What went wrong and what we did about it, written as it happened: [FRICTION_LOG.md](FRICTION_LOG.md).

## Hackathon tracks entered

- **Track 01, Agents That Act on Connected Data:** an AI intake step and an MCP server act on the graph through a small set of validated tools; the one write tool records a hazard, and dispatch stays a human action. There is no free-form agent loop.
- **Track 02, Agent Memory and Coordination:** the graph remembers hazards and earlier incidents per address, and that memory changes which units are sent; every decision and the memory it used are stored and explainable; unit assignment is all or nothing.

## Next

- Mutual aid between agencies.
- Road closures in the routing graph.
- HTTPS.

## License

MIT, see [LICENSE](LICENSE).
