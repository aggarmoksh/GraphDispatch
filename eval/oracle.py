"""Independent oracle for the Phase 7 evaluation.

Recomputes the answer to every scenario from the seed CSVs alone: haversine snapping, Dijkstra on travel_s (networkx),
and the dispatch rules reimplemented from their written definitions (eval/PROTOCOL.md section "Oracle").
Imports: standard library and networkx only. It must never import graphdispatch (a test enforces this).
"""
import csv
import math
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "seed"
EARTH_M = 6371008.8


def haversine(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(a))


def rows(path):
    """CSV rows as dicts; lines starting with '#' are comments."""
    with open(path, newline="", encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    return list(csv.DictReader(lines))


def split(v):
    return [x for x in (v or "").split(";") if x]


class World:
    """Everything the oracle knows, read from seed/ only."""

    def __init__(self, seed=SEED):
        snap_dir = sorted(Path(seed).glob("osm_b2_*"))[-1]
        self.nodes = [(int(r["osm_id"]), float(r["lat"]), float(r["lon"])) for r in rows(snap_dir / "b2_intersections.csv")]
        self.graph = nx.DiGraph()
        for r in rows(snap_dir / "b2_roads.csv"):
            self.graph.add_edge(int(r["src"]), int(r["dst"]), travel_s=float(r["travel_s"]))
        self.stations = {int(r["station_id"]): (float(r["lat"]), float(r["lon"])) for r in rows(Path(seed) / "stations.csv")}
        self.units = {r["unit_id"]: {"station_id": int(r["station_id"]), "status": r["status"], "capabilities": set(split(r["capabilities"])),
                                     "type": r["type"]} for r in rows(Path(seed) / "units.csv")}
        self.hospitals = [{"osm_id": int(r["osm_id"]), "name": r["name"], "lat": float(r["lat"]), "lon": float(r["lon"]),
                           "capabilities": set(split(r["capabilities"]))} for r in rows(Path(seed) / "hospitals.csv")]
        self.types = {}
        for r in rows(Path(seed) / "incident_types.csv"):
            self.types[r["name"]] = {
                "requires": {c.split(":")[0]: int(c.split(":")[1]) for c in split(r["requires"])},
                "destination": r["destination_capability"] or None,
                "fallback": r["fallback_capability"] or None,
                "max_extra_s": int(r["max_extra_s"]) if r["max_extra_s"] else None,
                "max_total_s": int(r["max_total_s"]) if r["max_total_s"] else None}
        self.hazard_rules = rows(Path(seed) / "hazard_rules.csv")
        self.hazard_crew_notes = {r["kind"]: r["crew_note"] for r in self.hazard_rules}

    def nearest(self, lat, lon, k=1):
        """The k nearest intersections as [(distance_m, osm_id)] by haversine."""
        return sorted((haversine(lat, lon, a, b), n) for n, a, b in self.nodes)[:k]

    def snap(self, lat, lon):
        d, n = self.nearest(lat, lon)[0]
        return n, d


def _status(world, busy):
    """Evaluation state: every unit available except the scenario's busy units (seed 'busy' flags are overridden)."""
    return {u: ("busy" if u in set(busy) else "available") for u in world.units}


def solve(scenario, world=None):
    """The oracle's answer for one scenario dict (see eval/scenarios.json)."""
    w = world or WORLD()
    t = w.types[scenario["incident_type"]]
    node, _ = w.snap(scenario["lat"], scenario["lon"])

    # requirements: base plus hazard additions, one count per hazard KIND (the max over rule rows for that capability)
    need = {c: {"need": n, "sources": ["base"]} for c, n in t["requires"].items()}
    added = {}
    for kind in set(scenario.get("hazards", [])):
        for r in w.hazard_rules:
            if r["kind"] == kind and r["incident_type"] == scenario["incident_type"] and r["adds_capability"]:
                key = (r["adds_capability"], kind)
                added[key] = max(added.get(key, 0), int(r["count"]))
    for (cap, kind), n in sorted(added.items()):
        e = need.setdefault(cap, {"need": 0, "sources": []})
        e["need"] += n
        e["sources"].append(f"hazard:{kind}")

    # travel times from every station intersection to the incident, over directed roads
    rev = w.graph.reverse(copy=False)
    dist_to_incident = nx.single_source_dijkstra_path_length(rev, node, weight="travel_s")
    status = _status(w, scenario.get("busy_units", []))
    station_node = {sid: w.snap(*latlon)[0] for sid, latlon in w.stations.items()}

    def eta(unit_id):
        return dist_to_incident.get(station_node[w.units[unit_id]["station_id"]])

    cands = {c: sorted((eta(u), u) for u, d in w.units.items()
                       if c in d["capabilities"] and status[u] == "available" and eta(u) is not None) for c in need}
    used, chosen, unmet = set(), [], []
    for cap in sorted(need, key=lambda c: (len(cands[c]), c)):      # scarcest capability first, ties by name
        picked = 0
        for e, u in cands[cap]:                                      # fastest first, a unit counted once
            if picked == need[cap]["need"]:
                break
            if u in used:
                continue
            used.add(u)
            chosen.append({"unit_id": u, "capability": cap, "eta_s": e, "station_id": w.units[u]["station_id"]})
            picked += 1
        if picked < need[cap]["need"]:
            unmet.append({"capability": cap, "missing": need[cap]["need"] - picked})
    chosen.sort(key=lambda x: (x["eta_s"], x["unit_id"]))

    # hospital: fastest offering the destination capability; stroke bypass rule from incident_types.csv
    hospital = nearest_h = None
    hospital_etas = {}
    rule = "no_destination"
    if t["destination"]:
        dist_from_incident = nx.single_source_dijkstra_path_length(w.graph, node, weight="travel_s")
        hs = []
        for h in w.hospitals:
            e = dist_from_incident.get(w.snap(h["lat"], h["lon"])[0])
            if e is not None:
                hs.append({**h, "eta_s": e})
                hospital_etas[h["name"]] = e
        hs.sort(key=lambda h: (h["eta_s"], h["osm_id"]))
        nearest_h = hs[0] if hs else None
        capable = next((h for h in hs if t["destination"] in h["capabilities"]), None)
        if t["fallback"]:
            fb = next((h for h in hs if t["fallback"] in h["capabilities"]), None)
            if capable is None:
                hospital, rule = fb, "no_capable"
            elif fb is None:
                hospital, rule = capable, "only_capable"
            elif capable["eta_s"] - fb["eta_s"] <= t["max_extra_s"] and capable["eta_s"] <= t["max_total_s"]:
                hospital, rule = capable, "bypass_used"
            else:
                hospital, rule = fb, "bypass_declined"
        else:
            hospital, rule = capable, "fastest_capable"

    def brief(h):
        return None if h is None else {"osm_id": h["osm_id"], "name": h["name"], "eta_s": h["eta_s"]}

    return {"incident_node": node, "requirements": need, "units": chosen, "unmet": unmet, "hospital": brief(hospital),
            "nearest_hospital": brief(nearest_h), "hospital_etas": hospital_etas, "hospital_rule": rule,
            "recall": {"hazards": sorted(set(scenario.get("hazards", []))), "prior_incident_types": sorted(scenario.get("prior_incidents", []))}}


_WORLD = None


def WORLD():
    global _WORLD
    if _WORLD is None:
        _WORLD = World()
    return _WORLD
