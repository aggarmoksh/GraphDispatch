"""Road closures: CLOSED_ROAD retyping, provenance, limits, expiry. Zero Bedrock calls."""
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from graphdispatch import api, closures, db, ops
from graphdispatch.closures import ClosureError
from graphdispatch.ops import run_call, why
from graphdispatch.recommend import recommend

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
client = TestClient(api.app)
S1 = (37.3300, -121.9300, "stroke")


def demo():
    rows = {r["role"]: r for r in api.demo_closures()}
    return rows["hospital_leg_detour"], rows["unit_change"]


def snapshot(rel="ROAD"):
    """Aggregate fingerprint of all edges of a type (the result-set limit is 10,000 rows, so full listings would truncate)."""
    n, t, ln, nm = db.graph().ro_query(f"MATCH ()-[r:{rel}]->() RETURN count(r), sum(r.travel_s), sum(r.length_m), count(r.name)").result_set[0]
    return (n, round(t or 0, 3), round(ln or 0, 3), nm)


def pair_props(rel, a, b):
    q = (f"MATCH (x:Intersection)-[r:{rel}]->(y:Intersection) WHERE (x.osm_id = $a AND y.osm_id = $b) OR (x.osm_id = $b AND y.osm_id = $a) "
         "RETURN x.osm_id, y.osm_id, r.travel_s, r.length_m, r.name")
    return sorted(tuple(x) for x in db.graph().ro_query(q, {"a": a, "b": b}).result_set)


def hospital_eta(rec):
    return rec["hospital"]["chosen"]["eta_s"]


@pytest.fixture(autouse=True)
def _limits():
    api._close_calls.clear()
    yield
    api._close_calls.clear()


def test_close_reopen_round_trip_restores_exact_edges_and_properties():
    before = snapshot()
    reroute, _ = demo()
    a_, b_ = reroute["src_osm"], reroute["dst_osm"]
    props = pair_props("ROAD", a_, b_)
    assert 1 <= len(props) <= 2
    cid = closures.close_road(a_, b_, "round trip")
    closed = pair_props("CLOSED_ROAD", a_, b_)
    assert closed == props                                          # same direction(s), travel_s, length_m and name
    assert pair_props("ROAD", a_, b_) == []                         # no ROAD edge left between the two intersections
    assert snapshot()[0] == before[0] - len(props) and snapshot("CLOSED_ROAD")[0] == len(props)
    assert db.graph().ro_query("MATCH (c:Closure {closure_id: $id})-[:AT]->(i:Intersection) RETURN count(i)", {"id": cid}).result_set[0][0] == 2
    assert db.graph().ro_query("MATCH ()-[r:CLOSED_ROAD {closure_id: $id}]->() RETURN count(r)", {"id": cid}).result_set[0][0] == len(props)
    assert closures.active_count() == 1
    closures.reopen_road(cid)
    assert snapshot() == before and snapshot("CLOSED_ROAD")[0] == 0   # exact counts and sums
    assert pair_props("ROAD", a_, b_) == props                        # exact properties
    assert closures.active_count() == 0
    with pytest.raises(ClosureError):
        closures.reopen_road(cid)                                  # already reopened
    cid2 = closures.close_road(a_, b_, "again")
    assert cid2 != cid
    with pytest.raises(ClosureError):
        closures.close_road(a_, b_, "twice")                       # already closed


def test_routes_never_contain_a_closed_pair():
    open_rec = recommend(*S1)
    for row in api.demo_closures():
        closures.close_road(row["src_osm"], row["dst_osm"], "route test")
    rec = recommend(*S1)
    closed_pairs = {frozenset((r["src_osm"], r["dst_osm"])) for r in api.demo_closures()}
    for route in rec["routes"]:
        for a, b in zip(route["nodes"], route["nodes"][1:]):
            assert frozenset((a, b)) not in closed_pairs, route["leg"]
    assert hospital_eta(rec) > hospital_eta(open_rec)               # the detour costs time
    assert rec["closures_active"] and not open_rec["closures_active"]


def test_decision_links_rerouted_around_with_extra_seconds():
    base = run_call("caller-a", "1 Open Rd", *S1)
    reroute, _ = demo()
    cid = closures.close_road(reroute["src_osm"], reroute["dst_osm"], reroute["reason"])
    out = run_call("caller-b", "2 Closed Rd", *S1)
    w = why(out["decision_id"])
    hosp = [x for x in w["rerouted"] if x["leg"] == "hospital"]
    assert len(hosp) == 1 and hosp[0]["closure_id"] == cid and hosp[0]["name"] == "Bayshore Freeway"
    expected = hospital_eta(out["recommendation"]) - hospital_eta(base["recommendation"])
    assert hosp[0]["extra_s"] > 0 and abs(hosp[0]["extra_s"] - expected) < 0.2
    n = db.graph().ro_query("MATCH (d:Decision {decision_id: $d})-[r:REROUTED_AROUND]->(c:Closure {closure_id: $c}) RETURN r.leg, r.extra_s",
                            {"d": out["decision_id"], "c": cid}).result_set
    assert n and n[0][0] == "hospital" and n[0][1] > 0
    text = ops.explain_why(w)
    assert "Rerouted around Bayshore Freeway (synthetic closure) for hospital: +" in text
    assert why(base["decision_id"])["rerouted"] == []               # earlier decisions are untouched


def test_changed_unit_is_recorded_and_explained():
    _, change = demo()
    base = run_call("caller-a", "1 Open Rd", *S1)
    assert {u["unit_id"] for u in base["recommendation"]["units"]} == {"E7", "M7"}
    closures.close_road(change["src_osm"], change["dst_osm"], change["reason"])
    out = run_call("caller-b", "2 Closed Rd", *S1)
    assert {u["unit_id"] for u in out["recommendation"]["units"]} == {"E10", "M10"}
    w = why(out["decision_id"])
    ch = {c["capability"]: c for c in w["changes"]["units"]}
    assert ch["als"]["without"] == ["E7"] and ch["als"]["with"] == ["E10"] and ch["transport"]["without"] == ["M7"]
    assert ch["als"]["with_eta"][0] > ch["als"]["without_eta"][0]
    assert "Without the closure, E7 would have covered als" in ops.explain_why(w)
    assert w["rerouted"] == []                                      # other stations took over: no chosen leg detours


def test_both_demo_closures_together_reroute_and_change_units():
    for row in api.demo_closures():
        closures.close_road(row["src_osm"], row["dst_osm"], row["reason"])
    w = why(run_call("caller-b", "2 Closed Rd", *S1)["decision_id"])
    assert any(x["leg"] == "hospital" and x["extra_s"] > 0 for x in w["rerouted"]) and w["changes"]["units"]


def test_hospital_change_is_recorded_when_a_closure_flips_the_choice():
    # closing every road out of the nearest capable hospital's neighbourhood is not needed: use the incident-side ring instead
    out = run_call("caller-a", "1 Open Rd", 37.3100, -121.8600, "pediatric_trauma")
    assert why(out["decision_id"])["changes"] == {"units": [], "hospital": None}       # no closures: nothing to compare


def test_no_closures_leaves_the_decision_unchanged():
    rec = recommend(*S1)
    assert rec["rerouted"] == [] and rec["changes"] == {"units": [], "hospital": None} and rec["no_route"] == []


def test_unreachable_leg_is_reported_not_a_crash():
    node = db.read("snap_incident", {"lat": S1[0], "lon": S1[1]})[0][0]
    neigh = db.graph().ro_query("MATCH (a:Intersection {osm_id: $n})-[:ROAD]-(b:Intersection) RETURN DISTINCT b.osm_id", {"n": node}).result_set
    for (b,) in neigh:
        try:
            closures.close_road(node, b, "isolate")
        except ClosureError:
            closures.close_road(b, node, "isolate")
    rec = recommend(*S1)                                            # must not raise
    assert rec["units"] == [] and "hospital" in rec["no_route"] and rec["hospital"]["chosen"] is None
    assert rec["no_route"][0] != "hospital" and rec["unmet"]
    out = run_call("caller-c", "3 Island Rd", *S1)
    w = why(out["decision_id"])
    assert "hospital" in w["no_route"]
    assert "No route: hospital" in ops.explain_why(w)
    r = client.post("/api/recommend", json={"lat": S1[0], "lon": S1[1], "incident_type": "stroke"})
    assert r.status_code == 200 and "hospital" in r.json()["no_route"]


def test_expired_closures_reopen():
    before = snapshot()
    reroute, _ = demo()
    now = int(time.time())
    cid = closures.close_road(reroute["src_osm"], reroute["dst_osm"], "old", now=now - 3600, expire_min=30)
    young = closures.close_road(*[api.demo_closures()[1][k] for k in ("src_osm", "dst_osm")], "young", now=now)
    assert closures.expire_closures(now) == 1
    assert [c["closure_id"] for c in closures.list_closures()] == [young]
    assert snapshot()[0] == before[0] - snapshot("CLOSED_ROAD")[0]
    closures.reopen_road(young)
    assert snapshot() == before


def test_sweeper_reopens_expired_closures_at_startup(monkeypatch):
    monkeypatch.setenv("DEMO_EXPIRY_INTERVAL_S", "3600")
    reroute, _ = demo()
    closures.close_road(reroute["src_osm"], reroute["dst_osm"], "old", now=int(time.time()) - 7200, expire_min=30)
    assert closures.active_count() == 1
    with TestClient(api.app) as c:
        for _ in range(50):
            if closures.active_count() == 0:
                break
            time.sleep(0.1)
        assert closures.active_count() == 0 and c.get("/api/health").status_code == 200


def test_loader_does_not_undo_a_closure():
    import load
    reroute, _ = demo()
    closures.close_road(reroute["src_osm"], reroute["dst_osm"], "restart")
    n = snapshot()
    load.load()                                                     # what happens on every app start
    assert snapshot() == n and closures.active_count() == 1


# ---------------------------------------------------------------- API
def test_api_close_by_point_list_and_reopen():
    r = client.post("/api/closures", json={"lat": 37.3340, "lon": -121.9200, "reason": "Click test"})
    assert r.status_code == 200
    c = r.json()["closure"]
    assert c["reason"] == "Click test" and c["synthetic"] and len(c["geometry"]) == 2 and r.json()["snapped_m"] < 400
    names = {q["name"] for q in r.json()["queries"]}
    assert "nearest_road_segment" in names and "close_road" in names and "Closure" in r.json()["closure_queries"]["close_road"]
    lst = client.get("/api/closures").json()
    assert [x["closure_id"] for x in lst["closures"]] == [c["closure_id"]] and lst["limit"] == 3 and lst["closures"][0]["geometry"][0][0] < -121
    assert client.delete(f"/api/closures/{c['closure_id']}").status_code == 200
    assert client.get("/api/closures").json()["closures"] == []
    assert client.delete(f"/api/closures/{c['closure_id']}").status_code == 404


def test_api_close_by_pair_and_validation():
    reroute, _ = demo()
    ok = client.post("/api/closures", json={"src_osm": reroute["src_osm"], "dst_osm": reroute["dst_osm"], "reason": reroute["reason"]})
    assert ok.status_code == 200 and ok.json()["closure"]["name"] == "Bayshore Freeway"
    again = client.post("/api/closures", json={"src_osm": reroute["src_osm"], "dst_osm": reroute["dst_osm"]})
    assert again.status_code == 409 and "already closed" in again.json()["detail"]
    assert client.post("/api/closures", json={}).status_code == 422
    assert client.post("/api/closures", json={"lat": 37.3, "lon": -121.9, "src_osm": 1, "dst_osm": 2}).status_code == 422
    assert client.post("/api/closures", json={"lat": 37.3, "lon": -121.9, "reason": "x" * 81}).status_code == 422


def test_api_cap_of_three_active_closures():
    pairs = [(r[0], r[1]) for r in db.graph().ro_query("MATCH (a:Intersection)-[:ROAD]->(b:Intersection) WHERE a.osm_id < b.osm_id RETURN a.osm_id, b.osm_id LIMIT 4").result_set]
    ids = []
    for a, b in pairs[:3]:
        r = client.post("/api/closures", json={"src_osm": a, "dst_osm": b})
        assert r.status_code == 200
        ids.append(r.json()["closure"]["closure_id"])
    fourth = client.post("/api/closures", json={"src_osm": pairs[3][0], "dst_osm": pairs[3][1]})
    assert fourth.status_code == 409 and "3 roads are already closed" in fourth.json()["detail"] and "Reopen one" in fourth.json()["detail"]
    assert closures.active_count() == 3
    assert client.delete(f"/api/closures/{ids[0]}").status_code == 200
    assert client.post("/api/closures", json={"src_osm": pairs[3][0], "dst_osm": pairs[3][1]}).status_code == 200   # a slot is free again


def test_api_per_ip_limit_of_ten_close_actions(monkeypatch):
    monkeypatch.setenv("MAX_ACTIVE_CLOSURES", "50")
    pairs = [(r[0], r[1]) for r in db.graph().ro_query("MATCH (a:Intersection)-[:ROAD]->(b:Intersection) WHERE a.osm_id < b.osm_id RETURN a.osm_id, b.osm_id LIMIT 12").result_set]
    codes = [client.post("/api/closures", json={"src_osm": a, "dst_osm": b}).status_code for a, b in pairs[:11]]
    assert codes == [200] * 10 + [429]
    assert "Too many road closures" in client.post("/api/closures", json={"src_osm": pairs[11][0], "dst_osm": pairs[11][1]}).json()["detail"]
    assert client.get("/api/closures").status_code == 200            # reading is not limited


def test_api_decision_carries_rerouting_and_meta_has_the_demo_closures():
    meta = client.get("/api/meta").json()
    assert [r["role"] for r in meta["demo_closures"]] == ["hospital_leg_detour", "unit_change"]
    assert meta["demo_closures"][0]["reason"] == "Synthetic closure for the demo" and meta["closure_limits"]["max_active"] == 3
    for row in meta["demo_closures"]:
        assert client.post("/api/closures", json={"src_osm": row["src_osm"], "dst_osm": row["dst_osm"], "reason": row["reason"]}).status_code == 200
    d = client.post("/api/recommend", json={"lat": S1[0], "lon": S1[1], "incident_type": "stroke"}).json()
    assert any(x["leg"] == "hospital" and x["extra_s"] > 0 and x["name"] == "Bayshore Freeway" for x in d["rerouted"])
    assert d["changes"]["units"] and d["no_route"] == []
    names = {q["name"] for q in d["queries"]}
    assert {"route_all", "eta_all", "decision_rerouted", "active_closure_count"} <= names
    again = client.get(f"/api/decision/{d['decision_id']}").json()
    assert again["rerouted"] == d["rerouted"] and again["changes"] == d["changes"]
