# Phase 0 Report (2026-10-15)

Verdict: SPpaths works and matches networkx on 20/20 pairs, fast and small. One acceptance miss: 874 intersections (< 1,000). 

| Item | Result |
|---|---|
| Python / Docker / Node / Git | 3.12.4 (venv; default 3.10.0) / 29.8.2 server (27.5.1 client) / v22.16.0 / 2.46.0 |
| Packages | FalkorDB 1.8.0, osmnx 2.1.1, networkx 3.7, python-dotenv 1.2.4 (requirements.txt) |
| Engine | FalkorDB graph module 42201 (4.22.1), image falkordb/falkordb@sha256:b0bdcac2cbaff989e77cb0610439b7a9289e86de033ccbbd4368b66fb680ae7a |
| algo.* procedures | AStar, BFS, HarmonicCentrality, MSF, SPpaths, SSpaths, WCC, betweenness, labelPropagation, maxFlow, pageRank (26 procedures total) |
| Synthetic test | PASS: A,B,C,D,E weight 40 (4 hops; direct A->E costs 100) |
| OSM | 874 nodes; edges 2,145 before and 2,145 after dedupe (0 dropped) |
| Load | 0.22 s; graph readback 874 nodes, 2,145 edges; rerun identical |
| Memory | GRAPH.MEMORY USAGE total 0 MB (integer MB); used_memory delta 1,092,880 B (~1.04 MB) |
| SPpaths vs networkx | 20/20 within 0.01 s; max abs_diff 4.5e-13 (largest SCC 845 of 874 nodes) |
| SPpaths latency | p50 0.9 ms, p95 1.5 ms, max 1.8 ms |
| AStar | exists, errored: requires 1 argument, got 3 (not debugged) |

## Acceptance
- Intersections 1,000-6,000: **FAIL** (874)
- Weight match >= 19/20: PASS (20/20)
- p95 < 300 ms: PASS (1.5 ms)
- Memory < 60 MB: PASS (~1 MB)
- Rerun identical counts: PASS

Note: default engine query TIMEOUT is 1000 ms (MODULE LIST args).
