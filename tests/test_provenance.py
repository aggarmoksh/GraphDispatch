"""Provenance, dispatch and latency. networkx is allowed here only, as oracle for route edges."""
import json
import math
import statistics
import time
from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

from graphdispatch import db, ops
from graphdispatch.ops import DispatchRefused, clear, dispatch, run_call, why
from graphdispatch.recommend import recommend

ROOT = Path(__file__).resolve().parent.parent
SNAP = sorted((ROOT / "seed").glob("osm_b2_*"))[-1]

S1 = ("caller-s1", "1 Stroke St", 37.3300, -121.9300, "stroke")
S4 = ("caller-s4", "2 Fire Rd", 37.3450, -121.8800, "structure_fire")


@pytest.fixture(scope="module")
def G():
    g = nx.DiGraph()
    for r in pd.read_csv(SNAP / "b2_roads.csv", keep_default_na=False).itertuples():
        g.add_edge(r.src, r.dst, w=r.travel_s)
    return g


def statuses():
    return dict(db.read("unit_statuses"))


def test_t3_why_equals_recommend_s1(G):
    rec = recommend(*S1[2:4], S1[4])
    out = run_call(*S1)
    w = why(out["decision_id"])
    print(ops.explain_why(w))
    assert [(u["unit_id"], u["capability"]) for u in out["recommendation"]["units"]] == [(u["unit_id"], u["capability"]) for u in rec["units"]]
    got = {u["unit_id"]: u for u in w["chose"]}
    assert set(got) == {u["unit_id"] for u in rec["units"]}
    for u in rec["units"]:
        assert abs(got[u["unit_id"]]["eta_s"] - u["eta_s"]) <= 0.01
        assert got[u["unit_id"]]["capability"] == u["capability"]
    assert w["destination"]["name"] == "Regional Medical Center of San Jose"
    assert abs(w["destination"]["eta_s"] - rec["hospital"]["chosen"]["eta_s"]) <= 0.01
    sk = {s["name"]: s for s in w["skipped"]}
    assert "O'Connor Hospital" in sk and "lacks stroke_thrombectomy" in sk["O'Connor Hospital"]["reason"]
    assert w["rule_applied"] == rec["rule_applied"]
    assert "+502 s over O'Connor Hospital" in w["rule_applied"] and "within 1800 s AHA bypass limit" in w["rule_applied"]
    assert w["agent"] == "deterministic-v1"
    # considered: top 5 per required capability, ranked 1..n
    for cap in {c["capability"] for c in w["considered"]}:
        ranks = [c["rank"] for c in w["considered"] if c["capability"] == cap]
        assert ranks == list(range(1, len(ranks) + 1)) and len(ranks) <= 5
    # routes: contiguous seq from 0 per leg, consecutive nodes joined by a ROAD edge, weight equals ETA
    legs = {}
    for r in w["route"]:
        legs.setdefault(r["leg"], []).append(r)
    assert set(legs) == {u["unit_id"] for u in rec["units"]} | {"hospital"}
    for leg, rows in legs.items():
        rows.sort(key=lambda r: r["seq"])
        assert [r["seq"] for r in rows] == list(range(len(rows)))
        nodes = [r["node"] for r in rows]
        total = 0.0
        for a, b in zip(nodes, nodes[1:]):
            assert G.has_edge(a, b)
            total += G[a][b]["w"]
        eta = w["destination"]["eta_s"] if leg == "hospital" else got[leg]["eta_s"]
        assert abs(total - eta) <= 0.01
        if leg == "hospital":
            assert nodes[0] == out["recommendation"]["incident"]["node"]
        else:
            assert nodes[-1] == out["recommendation"]["incident"]["node"]


def test_t4_dispatch_excludes_assigned_units_and_clear_restores():
    before = statuses()
    first = run_call(*S4)
    assigned = {u["unit_id"] for u in first["recommendation"]["units"]}
    assert dispatch(first["decision_id"]) == len(assigned)
    st = statuses()
    assert all(st[u] == "assigned" for u in assigned)
    assert why(first["decision_id"])["incident"]["status"] == "dispatched"
    second = run_call("caller-s4b", "3 Fire Rd", 37.3455, -121.8805, "structure_fire")
    chosen2 = {u["unit_id"] for u in second["recommendation"]["units"]}
    assert chosen2 and not (chosen2 & assigned)
    assert clear(first["incident_id"]) == len(assigned)
    assert statuses() == before
    assert why(first["decision_id"])["incident"]["status"] == "cleared"


def test_t5_dispatch_refuses_without_partial_writes():
    out = run_call(*S4)
    chosen = [u["unit_id"] for u in out["recommendation"]["units"]]
    assert len(chosen) >= 2
    db.write("set_unit_status", {"unit_id": chosen[-1], "status": "assigned"})
    before = statuses()
    with pytest.raises(DispatchRefused):
        dispatch(out["decision_id"])
    assert statuses() == before
    assert why(out["decision_id"])["incident"]["status"] == "open"
    assert db.read("assigned_to_count")[0][0] == 0


def test_dispatch_twice_refused():
    out = run_call(*S4)
    dispatch(out["decision_id"])
    with pytest.raises(DispatchRefused):
        dispatch(out["decision_id"])


def test_latency_why_and_run_call():
    scen = [S1, S4, ("c", "a1", 37.3600, -121.8550, "burn"), ("c", "a2", 37.3360, -121.8900, "cardiac_arrest"),
            ("c", "a3", 37.3100, -121.8600, "pediatric_trauma"), ("c", "a4", 37.3200, -121.9100, "hazmat_spill")]
    call_ms, why_ms = [], []
    for i in range(20):
        s = scen[i % len(scen)]
        t0 = time.perf_counter()
        out = run_call(*s)
        call_ms.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        why(out["decision_id"])
        why_ms.append((time.perf_counter() - t0) * 1000)

    def pct(x, q):
        x = sorted(x)
        return x[math.ceil(q * len(x)) - 1]

    res = {"run_call_p50_ms": statistics.median(call_ms), "run_call_p95_ms": pct(call_ms, .95),
           "why_p50_ms": statistics.median(why_ms), "why_p95_ms": pct(why_ms, .95), "n": 20}
    (ROOT / "phase2").mkdir(exist_ok=True)
    (ROOT / "phase2" / "latency.json").write_text(json.dumps(res, indent=1))
    print(res)
    assert res["why_p95_ms"] < 50
    assert res["run_call_p95_ms"] < 300
