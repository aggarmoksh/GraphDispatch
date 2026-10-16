"""API tests with FastAPI's TestClient. Zero Bedrock calls: llm.converse is monkeypatched."""
import json
import math
import statistics
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from graphdispatch import api, db, llm

client = TestClient(api.app)
ROOT = Path(__file__).resolve().parent.parent
LAT, LON = 37.3360, -121.8900
BBOX = (-121.945, 37.30, -121.84, 37.37)  # west, south, east, north


def canned(incident_type, hazards=(), address_label=None):
    def fake(system, messages, tools=None, max_tokens=300, force_tool=None, model_id=None):
        return {"tool_name": "classify_call", "text": "", "stop_reason": "tool_use", "input_tokens": 1, "output_tokens": 1,
                "latency_ms": 1.0,
                "tool_input": {"incident_type": incident_type, "hazards": list(hazards), "address_label": address_label,
                               "confidence": 0.95, "reason": "canned"}}
    return fake


@pytest.fixture(autouse=True)
def _isolated_caps(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DAILY_FILE", tmp_path / "llm_daily.json")
    monkeypatch.setenv("LLM_DAILY_CAP", "1000")
    api._ip_calls.clear()


def recommend(itype="stroke", lat=37.3300, lon=-121.9300, address=""):
    return client.post("/api/recommend", json={"lat": lat, "lon": lon, "incident_type": itype, "address": address})


def test_health_ok_and_503_when_database_unreachable(monkeypatch):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] and r.json()["intersections"] == 4213
    monkeypatch.setenv("FALKORDB_PORT", "1")  # closed port
    db.reset_connection()
    try:
        bad = client.get("/api/health")
        assert bad.status_code == 503 and bad.json()["ok"] is False
        assert "FalkorDB" in bad.json()["error"]
    finally:
        monkeypatch.undo()
        db.reset_connection()
    assert client.get("/api/health").status_code == 200


def test_meta():
    m = client.get("/api/meta").json()
    assert m["graph"] == "sjfd_test"
    assert len(m["stations"]) == 10 and len(m["hospitals"]) == 3 and len(m["units"]) == 22
    assert len(m["incident_types"]) == 7 and set(m["hazard_kinds"]) == {"oxygen_storage", "aggressive_dog"}
    scvmc = next(h for h in m["hospitals"] if h["osm_id"] == 609630707)
    assert scvmc["levels"]["trauma"] == "I" and "burn" in scvmc["capabilities"]
    assert m["counts"]["nodes"]["Intersection"] == 4213
    text = json.dumps(m)
    assert "AWS_" not in text and "SECRET" not in text.upper()


def test_recommend_includes_routes_and_real_cypher():
    r = recommend()
    assert r.status_code == 200
    d = r.json()
    assert d["destination"]["name"] == "Regional Medical Center of San Jose"
    legs = {x["leg"]: x for x in d["routes"]}
    assert "hospital" in legs and legs["hospital"]["kind"] == "hospital"
    assert {u["unit_id"] for u in d["units"]} <= set(legs)
    for route in d["routes"]:
        assert len(route["coords"]) >= 2
        for lon, lat in route["coords"]:
            assert BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]   # [lon, lat] order
    names = {q["name"] for q in d["queries"]}
    assert {"unit_candidates", "eta", "effective_requirements", "hospitals", "dest_capability", "recall_hazards",
            "recall_incidents", "why"} <= names
    for q in d["queries"]:
        assert q["cypher"] == db.queries()[q["name"]] and "MATCH" in q["cypher"].upper() and q["ms"] >= 0
    assert d["total_ms"] > 0 and d["incident"]["status"] == "open" and d["synthetic"] is True


def test_recommend_validation():
    assert recommend("alien_attack").status_code == 422
    out = recommend("stroke", lat=37.45, lon=-121.90)
    assert out.status_code == 422 and "outside the mapped area" in out.json()["detail"]
    assert client.post("/api/recommend", json={"lat": 999, "lon": 0, "incident_type": "stroke"}).status_code == 422


def test_decision_get_and_404():
    d = recommend().json()
    g = client.get(f"/api/decision/{d['decision_id']}")
    assert g.status_code == 200 and g.json()["decision_id"] == d["decision_id"]
    assert g.json()["routes"] and g.json()["queries"][0]["name"] == "why"
    assert client.get("/api/decision/dec-nope").status_code == 404


def test_dispatch_clear_and_incidents():
    d = recommend("structure_fire", lat=37.345, lon=-121.88).json()
    inc = d["incident"]["incident_id"]
    assert [i["incident_id"] for i in client.get("/api/incidents").json()["incidents"]] == [inc]
    r = client.post(f"/api/dispatch/{d['decision_id']}")
    assert r.status_code == 200 and r.json()["incident"]["status"] == "dispatched"
    again = client.post(f"/api/dispatch/{d['decision_id']}")
    assert again.status_code == 409 and "Nothing was changed" in again.json()["detail"]
    status = {u["unit_id"]: u["status"] for u in client.get("/api/incidents").json()["units"]}
    assert all(status[u["unit_id"]] == "assigned" for u in d["units"])
    c = client.post(f"/api/clear/{inc}")
    assert c.status_code == 200 and c.json()["units_released"] == len(d["units"])
    status = {u["unit_id"]: u["status"] for u in client.get("/api/incidents").json()["units"]}
    assert all(status[u["unit_id"]] == "available" for u in d["units"])
    assert client.post("/api/clear/inc-nope").status_code == 404
    assert client.post("/api/dispatch/dec-nope").status_code == 404


def test_hazard_endpoint_changes_the_next_decision():
    assert client.post("/api/hazard", json={"address": "200 Demo Street", "kind": "unicorns", "note": "x"}).status_code == 422
    ok = client.post("/api/hazard", json={"address": "200 Demo Street", "kind": "oxygen_storage", "note": "oxygen tanks",
                                          "lat": LAT, "lon": LON})
    assert ok.status_code == 200 and ok.json()["hazard_id"].startswith("haz-")
    hz = client.get("/api/incidents").json()["hazards"]
    assert [(h["kind"], h["lat"], h["lon"]) for h in hz] == [("oxygen_storage", LAT, LON)]
    d = recommend("structure_fire", LAT, LON, address="200 demo st.").json()
    units = {u["unit_id"]: u for u in d["units"]}
    assert "HM26" in units and "oxygen_storage" in units["HM26"]["reason_text"]
    assert d["recalled_hazard_groups"][0]["kind"] == "oxygen_storage"
    assert "Stored oxygen" in d["recalled_hazard_groups"][0]["crew_note"]


def test_call_uses_canned_llm_and_returns_classification_without_confidence(monkeypatch):
    monkeypatch.setattr(llm, "converse", canned("structure_fire", ["oxygen_storage"], "200 Demo Street"))
    r = client.post("/api/call", json={"text": "smoke, my neighbor uses home oxygen", "lat": LAT, "lon": LON})
    assert r.status_code == 200
    d = r.json()
    assert d["classification"]["incident_type"] == "structure_fire" and "confidence" not in d["classification"]
    assert "HM26" in {u["unit_id"] for u in d["units"]}
    assert d["queries"] and d["routes"]


def test_call_rejected_output_is_422(monkeypatch):
    monkeypatch.setattr(llm, "converse", canned("alien_attack"))
    r = client.post("/api/call", json={"text": "strange lights", "lat": LAT, "lon": LON})
    assert r.status_code == 422 and "nothing was saved" in r.json()["detail"]
    assert client.get("/api/incidents").json()["incidents"] == []


def test_daily_cap_zero_blocks_call_but_graph_only_still_works(monkeypatch):
    monkeypatch.setattr(llm, "converse", canned("stroke"))
    monkeypatch.setenv("LLM_DAILY_CAP", "0")
    r = client.post("/api/call", json={"text": "face drooping", "lat": 37.33, "lon": -121.93})
    assert r.status_code == 429 and "Switch to Graph only" in r.json()["detail"]
    assert recommend().status_code == 200


def test_per_ip_limit(monkeypatch):
    monkeypatch.setattr(llm, "converse", canned("stroke"))
    codes = [client.post("/api/call", json={"text": "face drooping", "lat": 37.33, "lon": -121.93}).status_code for _ in range(7)]
    assert codes == [200] * 6 + [429]
    assert recommend().status_code == 200


def test_daily_counter_persists_by_utc_date(monkeypatch):
    monkeypatch.setattr(llm, "converse", canned("stroke"))
    monkeypatch.setenv("LLM_DAILY_CAP", "2")
    codes = []
    for _ in range(3):
        api._ip_calls.clear()
        codes.append(client.post("/api/call", json={"text": "face drooping", "lat": 37.33, "lon": -121.93}).status_code)
    assert codes == [200, 200, 429]
    saved = json.loads(api.DAILY_FILE.read_text())
    assert saved["count"] == 2 and len(saved["date"]) == 10


def test_static_page_and_vendored_assets():
    page = client.get("/")
    assert page.status_code == 200 and "GraphDispatch" in page.text
    assert "Every recommendation is a walk through a FalkorDB graph of San Jose roads, stations and hospitals." in page.text
    for path in ("/app.js", "/map.js", "/panel.js", "/api.js", "/style.css", "/vendor/maplibre-gl.js", "/vendor/maplibre-gl.css"):
        assert client.get(path).status_code == 200, path
    # no secrets in static files
    for f in (ROOT / "graphdispatch" / "static").glob("*.*"):
        assert "AKIA" not in f.read_text(encoding="utf-8")


def test_recommend_latency_p95():
    ms = []
    import time
    for _ in range(20):
        t0 = time.perf_counter()
        assert recommend().status_code == 200
        ms.append((time.perf_counter() - t0) * 1000)
    ms.sort()
    p50, p95 = statistics.median(ms), ms[math.ceil(0.95 * len(ms)) - 1]
    (ROOT / "runs").mkdir(exist_ok=True)
    (ROOT / "runs" / "api_latency.json").write_text(json.dumps({"n": 20, "p50_ms": p50, "p95_ms": p95}, indent=1))
    assert p95 < 300
