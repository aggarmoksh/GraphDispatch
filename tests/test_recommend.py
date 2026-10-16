"""Scenario tests. networkx is allowed here only, as an oracle on b2_roads.csv."""
import json
import math
import statistics
import sys
from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from graphdispatch.recommend import OutOfArea, recommend  # noqa: E402

SEED, OUT = ROOT / "seed", ROOT / "runs"
SNAP = sorted(SEED.glob("osm_b2_*"))[-1]

SCENARIOS = {
    "S1": ("stroke", 37.3300, -121.9300),
    "S2": ("burn", 37.3600, -121.8550),
    "S3": ("cardiac_arrest", 37.3360, -121.8900),
    "S4": ("structure_fire", 37.3450, -121.8800),
    "S5": ("pediatric_trauma", 37.3100, -121.8600),
    "S6": ("hazmat_spill", 37.3200, -121.9100),
    "S7": ("cardiac_arrest", 37.4500, -121.9000),
}


def hav(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742000 * math.asin(math.sqrt(a))


@pytest.fixture(scope="module")
def world():
    nodes = pd.read_csv(SNAP / "b2_intersections.csv")
    roads = pd.read_csv(SNAP / "b2_roads.csv", keep_default_na=False)
    G = nx.DiGraph()
    for r in roads.itertuples():
        G.add_edge(r.src, r.dst, w=r.travel_s)
    lat, lon, ids = nodes.lat.values, nodes.lon.values, nodes.osm_id.values

    def snap(la, lo):
        d = [hav(la, lo, a, b) for a, b in zip(lat, lon)]
        i = min(range(len(d)), key=d.__getitem__)
        return int(ids[i]), d[i]

    stations = pd.read_csv(SEED / "stations.csv", comment="#")
    units = pd.read_csv(SEED / "units.csv", comment="#")
    types = pd.read_csv(SEED / "incident_types.csv", comment="#", dtype=str).fillna("")
    hosp = pd.read_csv(SEED / "hospitals.csv", comment="#", dtype={"osm_id": int}).set_index("osm_id", drop=False)
    return dict(G=G, snap=snap, units=units.set_index("unit_id"), types=types.set_index("name"),
                st_node={int(r.station_id): snap(r.lat, r.lon)[0] for r in stations.itertuples()},
                hosp={int(r.osm_id): (snap(r.lat, r.lon)[0], set(r.capabilities.split(";")))
                      for r in hosp.itertuples()})


def dist(G, a, b):
    return 0.0 if a == b else nx.dijkstra_path_length(G, a, b, weight="w")


RECORD = {}


@pytest.mark.parametrize("sid", [s for s in SCENARIOS if s != "S7"])
def test_scenario(sid, world):
    itype, lat, lon = SCENARIOS[sid]
    r = recommend(lat, lon, itype)
    node, _ = world["snap"](lat, lon)
    assert r["incident"]["node"] == node
    G, units = world["G"], world["units"]
    covered = {}
    assert len({u["unit_id"] for u in r["units"]}) == len(r["units"])
    for u in r["units"]:
        row = units.loc[u["unit_id"]]
        assert row.status == "available"
        assert u["capability"] in row.capabilities.split(";")
        assert abs(u["eta_s"] - dist(G, world["st_node"][int(row.station_id)], node)) <= 0.01
        covered[u["capability"]] = covered.get(u["capability"], 0) + 1
    for part in world["types"].loc[itype, "requires"].split(";"):
        cap, n = part.split(":")
        assert covered.get(cap, 0) == int(n), f"{cap} short"
    assert not r["unmet"]
    h = r["hospital"]
    if world["types"].loc[itype, "destination_capability"]:
        need = world["types"].loc[itype, "destination_capability"]
        assert need in world["hosp"][h["chosen"]["osm_id"]][1]
        assert abs(h["chosen"]["eta_s"] - dist(G, node, world["hosp"][h["chosen"]["osm_id"]][0])) <= 0.01
        best = min(dist(G, node, hn) for hn, caps in world["hosp"].values() if need in caps)
        assert abs(h["chosen"]["eta_s"] - best) <= 0.01
        nearest = min(dist(G, node, hn) for hn, _ in world["hosp"].values())
        assert abs(h["nearest"]["eta_s"] - nearest) <= 0.01
    else:
        assert h is None
    RECORD[sid] = {"type": itype, "units": [(u["unit_id"], u["capability"], round(u["eta_s"], 1)) for u in r["units"]],
                   "chosen": h and h["chosen"]["name"], "nearest": h and h["nearest"]["name"],
                   "differs": h and h["differs_from_nearest"], "skipped": h and h["skipped_reason"],
                   "total_ms": round(r["timings_ms"]["total"], 1)}


def test_s7_out_of_area():
    itype, lat, lon = SCENARIOS["S7"]
    with pytest.raises(OutOfArea):
        recommend(lat, lon, itype)


def test_latency_p95():
    lat_ms = []
    for sid, (itype, lat, lon) in SCENARIOS.items():
        if sid == "S7":
            continue
        for _ in range(5):
            lat_ms.append(recommend(lat, lon, itype)["timings_ms"]["total"])
    lat_ms.sort()
    p50, p95 = statistics.median(lat_ms), lat_ms[math.ceil(0.95 * len(lat_ms)) - 1]
    OUT.mkdir(exist_ok=True)
    (OUT / "results.json").write_text(json.dumps({"scenarios": RECORD, "p50_ms": p50, "p95_ms": p95, "n": len(lat_ms)}, indent=1))
    assert p95 < 300
