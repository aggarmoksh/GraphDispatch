"""Pick the demo closure for the preset "Road closed on the stroke route" (graph only, no Bedrock).

Candidates are the segments on S1's routes (both unit routes and the hospital route). For each, close both directions in a copy
of the road graph and re-solve S1 with the independent oracle (eval/oracle.py, networkx). Every leg must stay reachable and at least
one CHOSEN leg must really route around the closure (so the decision can say "rerouted around X, +N s"). Among those, prefer a
closure that also changes the chosen unit or hospital, then the one that adds the most seconds. Writes seed/demo_closures.csv.
Run: python phase9/find_demo_closure.py
"""
import copy
import csv
import json
import sys
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
import oracle  # noqa: E402

scen = {s["id"]: s for s in json.loads((ROOT / "eval" / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]}
sc = scen["S1"]
w = oracle.World()
snap_dir = sorted((ROOT / "seed").glob("osm_b2_*"))[-1]
names = {}
for r in oracle.rows(snap_dir / "b2_roads.csv"):
    names[(int(r["src"]), int(r["dst"]))] = r["name"]

base = oracle.solve(sc, w)
inc = base["incident_node"]
station_node = {sid: w.snap(*ll)[0] for sid, ll in w.stations.items()}
paths = []
for u in base["units"]:
    paths.append((u["unit_id"], nx.shortest_path(w.graph, station_node[u["station_id"]], inc, weight="travel_s")))
hospital_node = next(w.snap(h["lat"], h["lon"])[0] for h in w.hospitals if h["name"] == base["hospital"]["name"])
paths.append(("hospital", nx.shortest_path(w.graph, inc, hospital_node, weight="travel_s")))

pairs = {}
for leg, nodes in paths:
    for a, b in zip(nodes, nodes[1:]):
        pairs.setdefault(frozenset((a, b)), []).append(leg)

rev_free = w.graph.reverse(copy=False)
free_unit = nx.single_source_dijkstra_path_length(rev_free, inc, weight="travel_s")
free_hosp = nx.single_source_dijkstra_path_length(w.graph, inc, weight="travel_s")
hnode = {h["name"]: w.snap(h["lat"], h["lon"])[0] for h in w.hospitals}


def rerouted_extra(r, g2):
    """Seconds the CHOSEN legs of result r lose compared with the same legs on the open road graph (their detour)."""
    closed_unit = nx.single_source_dijkstra_path_length(g2.reverse(copy=False), inc, weight="travel_s")
    extra = 0.0
    for u in r["units"]:
        n = station_node[u["station_id"]]
        extra += max(0.0, closed_unit[n] - free_unit[n])
    if r["hospital"]:
        closed_h = nx.single_source_dijkstra_path_length(g2, inc, weight="travel_s")
        extra += max(0.0, closed_h[hnode[r["hospital"]["name"]]] - free_hosp[hnode[r["hospital"]["name"]]])
    return extra


results, changers = [], []
for pair, legs in pairs.items():
    a, b = sorted(pair)
    g2 = w.graph.copy()
    for x, y in ((a, b), (b, a)):
        if g2.has_edge(x, y):
            g2.remove_edge(x, y)
    w2 = copy.copy(w)
    w2.graph = g2
    r = oracle.solve(sc, w2)
    if r["unmet"] or r["hospital"] is None or len(r["units"]) != len(base["units"]):
        continue                                            # something became unreachable: not a good demo
    d_units = sum(u["eta_s"] for u in r["units"]) - sum(u["eta_s"] for u in base["units"])
    d_hosp = r["hospital"]["eta_s"] - base["hospital"]["eta_s"]
    changed_units = {u["unit_id"] for u in r["units"]} != {u["unit_id"] for u in base["units"]}
    changed_hosp = r["hospital"]["name"] != base["hospital"]["name"]
    extra = rerouted_extra(r, g2)
    name = names.get((a, b)) or names.get((b, a)) or ""
    if (changed_units or changed_hosp) and name:
        changers.append({"a": a, "b": b, "name": name, "d_units": d_units, "d_hosp": d_hosp, "units": [u["unit_id"] for u in r["units"]]})
    if extra <= 0.01:
        continue                                            # no chosen leg routes around it: the decision could not say "rerouted"
    score = extra + d_units + d_hosp + (1000 if (changed_units or changed_hosp) else 0)
    results.append({"score": score, "a": a, "b": b, "name": name, "legs": legs, "d_units": d_units, "d_hosp": d_hosp,
                    "changed_units": changed_units, "changed_hosp": changed_hosp, "rerouted_extra": extra,
                    "units": [(u["unit_id"], round(u["eta_s"], 1)) for u in r["units"]], "hospital": (r["hospital"]["name"], round(r["hospital"]["eta_s"], 1))})
results.sort(key=lambda x: (-round(x["score"], 1), 0 if x["name"] else 1))
print("baseline:", [(u["unit_id"], round(u["eta_s"], 1)) for u in base["units"]], base["hospital"]["name"], round(base["hospital"]["eta_s"], 1))
print(f"{len(pairs)} candidate segments, {len(results)} keep everything reachable and make a chosen leg route around the closure")
for r in results[:6]:
    print(f"  score {r['score']:.0f}: {r['name'] or '(unnamed)'} {r['a']}-{r['b']} on {r['legs']}: units {r['units']} (+{r['d_units']:.0f} s, chosen legs detour +{r['rerouted_extra']:.0f} s), "
          f"hospital {r['hospital']} (+{r['d_hosp']:.0f} s), unit changed {r['changed_units']}, hospital changed {r['changed_hosp']}")
best = next(r for r in results if r["name"])                 # the largest detour on a named road
changers.sort(key=lambda x: -(x["d_units"] + x["d_hosp"]))
second = changers[0]
print("best named reroute :", best["name"], best["a"], best["b"], f"(chosen legs detour +{best['rerouted_extra']:.0f} s)")
print("best unit changer  :", second["name"], second["a"], second["b"], "units become", second["units"], f"(+{second['d_units']:.0f} s)")

# both closed together must keep every leg reachable
g3 = w.graph.copy()
for pa, pb in ((best["a"], best["b"]), (second["a"], second["b"])):
    for x, y in ((pa, pb), (pb, pa)):
        if g3.has_edge(x, y):
            g3.remove_edge(x, y)
w3 = copy.copy(w)
w3.graph = g3
both = oracle.solve(sc, w3)
assert not both["unmet"] and both["hospital"] is not None, "closing both makes a leg unreachable"
print("both closed        : units", [(u["unit_id"], round(u["eta_s"], 1)) for u in both["units"]], "hospital", both["hospital"]["name"], round(both["hospital"]["eta_s"], 1))


def oriented(x):
    a, b = x["a"], x["b"]
    return (a, b) if (a, b) in names else (b, a)


out = ROOT / "seed" / "demo_closures.csv"
with out.open("w", newline="", encoding="utf-8") as f:
    wr = csv.writer(f, lineterminator="\n")
    wr.writerow(["preset", "scenario", "incident_type", "lat", "lon", "src_osm", "dst_osm", "name", "reason", "role"])
    for role, x in (("hospital_leg_detour", best), ("unit_change", second)):
        a, b = oriented(x)
        wr.writerow(["road_closed_on_stroke_route", "S1", sc["incident_type"], sc["lat"], sc["lon"], a, b, x["name"], "Synthetic closure for the demo", role])
print("wrote", out.relative_to(ROOT))
