# Friction Log

Entry format:
- `YYYY-MM-DD HH:MM` `[area]` What I tried. Expected X, got Y. Impact. Workaround.
- `2026-10-15 13:50` `[env]` Ran FalkorDB step with Docker CLI present. Expected Docker engine running, got pipe-not-found (Docker Desktop stopped). Impact: steps 3,5,6,7 paused until user started Docker. Workaround: user started Docker; resumed.
- `2026-10-15 13:50` `[osm]` Downloaded the specified downtown San Jose bbox. Expected 1,000-6,000 intersections, got 874 (2,145 edges). Impact: fails the acceptance range; bbox untouched per rules. Workaround: none, flagged for advisor (bbox likely needs widening).
- `2026-10-15 13:50` `[osm]` Expected parallel (src,dst) edges to be dropped by dedupe, got 0 dropped (2145 before and after). Impact: none; simplified osmnx graph had no parallel pairs in this bbox. Workaround: none needed.
- `2026-10-15 13:50` `[osm]` osmnx 2.1.1 graph_from_bbox takes one tuple (left, bottom, right, top). Expected the older north/south/east/west kwargs. Impact: none after checking signature. Workaround: pass (W,S,E,N) tuple.
- `2026-10-15 13:50` `[falkordb]` Called algo.AStar(a, b, {...}). Expected positional source/target/config, got "Procedure algo.AStar requires 1 arguments, got 3". Impact: no AStar columns in sp_compare.csv. Workaround: none, not debugged per instructions.
- `2026-10-15 13:50` `[falkordb]` GRAPH.MEMORY USAGE probe_roads. Expected MB figure with useful precision, got all zeros (values are integer MB, graph under 1 MB). Impact: memory check is only an upper bound. Workaround: INFO memory used_memory delta (1,092,880 bytes on first load).
