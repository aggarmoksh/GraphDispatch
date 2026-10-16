# AI Disclosure

Built with Claude Code as the coding assistant; design decisions and verification by the author.
- 2026-10-15 Phase 0: FalkorDB SPpaths probe (road graph, synthetic test, networkx oracle comparison).
- 2026-10-15 Phase 0B: choose map boundary from real hospital/fire station locations (OSM POIs, box counts) and probe algo.AStar.
- 2026-10-15 Phase 1: built the sjfd dispatch graph for box B2 and recommend() with tests.
- 2026-10-15 Phase 2: decision provenance, cross-call memory, human-confirmed dispatch and seed-only rebuild.
- 2026-10-15 Phase 3: hazard-driven requirements, trauma levels, safe reset script, test output moved to runs/.
- 2026-10-15 Phase 4A: Amazon Bedrock access and intake classification probe (forced tool call, graph-derived enums).
- 2026-10-16 Phase 4B: duplicate-hazard fix, installable package, LLM intake into the graph pipeline, address normalization, MCP server.
- 2026-10-16 Phase 5: FastAPI API, static MapLibre page with a Cypher-showing Why drawer, server-side LLM caps, Playwright visual check.
- 2026-10-16 Phase 5B: UI polish for the demo (skipped hospital on the map, plain labels, m:ss, map follows the decision).
