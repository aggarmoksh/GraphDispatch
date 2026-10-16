"""Exact numbers behind the README's closure claims (independent oracle, road snapshot, no graph, no Bedrock).
Run: python docs/phases/phase10/closure_numbers.py"""
import copy
import csv
import json
import sys
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "eval"))
import oracle  # noqa: E402

sc = next(s for s in json.loads((ROOT / "eval" / "scenarios.json").read_text(encoding="utf-8"))["scenarios"] if s["id"] == "S1")
w = oracle.World()
rows = list(csv.DictReader((ROOT / "seed" / "demo_closures.csv").open(encoding="utf-8")))
g = w.graph.copy()
for r in rows:
    for a, b in ((int(r["src_osm"]), int(r["dst_osm"])), (int(r["dst_osm"]), int(r["src_osm"]))):
        if g.has_edge(a, b):
            g.remove_edge(a, b)
w2 = copy.copy(w)
w2.graph = g


def station_etas(world):
    node, _ = world.snap(sc["lat"], sc["lon"])
    dist = nx.single_source_dijkstra_path_length(world.graph.reverse(copy=False), node, weight="travel_s")
    return {sid: dist[world.snap(*ll)[0]] for sid, ll in world.stations.items()}, node


open_e, node = station_etas(w)
closed_e, _ = station_etas(w2)
a, b = oracle.solve(sc, w), oracle.solve(sc, w2)
print("closures:", [(r["name"], r["role"]) for r in rows])
for s in (7, 10):
    print(f"station {s}: open {open_e[s]:.2f} s, with both closures {closed_e[s]:.2f} s")
print(f"difference station 7 minus station 10 with the closures: {closed_e[7] - closed_e[10]:.2f} s")
print("units before:", [(u['unit_id'], round(u['eta_s'], 1)) for u in a['units']], "after:", [(u['unit_id'], round(u['eta_s'], 1)) for u in b['units']])
print(f"hospital before {a['hospital']['name']} {a['hospital']['eta_s']:.2f} s, after {b['hospital']['name']} {b['hospital']['eta_s']:.2f} s, "
      f"detour {b['hospital']['eta_s'] - a['hospital']['eta_s']:.2f} s")
