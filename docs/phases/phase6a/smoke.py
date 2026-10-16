"""Smoke test of a running stack. Usage: python docs/phases/phase6a/smoke.py http://localhost:8080 [--calls 20]
Graph-only: it expects the AI path to be capped at 0 (LLM_DAILY_CAP=0) and verifies that, making no Bedrock call.
"""
import json
import sys
import time
import urllib.error
import urllib.request

base = sys.argv[1].rstrip("/")
calls = int(sys.argv[sys.argv.index("--calls") + 1]) if "--calls" in sys.argv else 0

SEED_NODES = {"Capability": 11, "Hospital": 3, "HazardKind": 2, "IncidentType": 7, "Intersection": 4213, "Station": 10, "Unit": 22}
SEED_RELS = {"ADDS_REQUIREMENT": 1, "BASED_AT": 22, "DESTINATION_NEEDS": 5, "HAS_CAPABILITY": 43, "LOCATED_AT": 13,
             "OFFERS": 10, "REQUIRES": 14, "ROAD": 10430}


def call(path, body=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, detail)


s, b = call("/api/health")
check("health 200", s == 200 and json.loads(b)["ok"], b)
s, b = call("/api/meta")
m = json.loads(b)
nodes, rels = m["counts"]["nodes"], m["counts"]["relationships"]
seed_nodes = {k: nodes.get(k) for k in SEED_NODES}
seed_rels = {k: rels.get(k) for k in SEED_RELS}
check("meta node counts equal the seed counts", seed_nodes == SEED_NODES, json.dumps(seed_nodes))
check("meta relationship counts equal the seed counts", seed_rels == SEED_RELS, json.dumps(seed_rels))
check("10 stations, 3 hospitals", len(m["stations"]) == 10 and len(m["hospitals"]) == 3)
s, b = call("/api/recommend", {"lat": 37.33, "lon": -121.93, "incident_type": "stroke"})
d = json.loads(b)
check("S1 recommend picks Regional", s == 200 and d["destination"]["name"] == "Regional Medical Center of San Jose",
      f"{d['destination']['name']} {d['destination']['eta_s']:.0f}s, skipped {d['skipped'][0]['name']}")
s, b = call("/")
check("page loads", s == 200 and "GraphDispatch" in b)
s, b = call("/vendor/maplibre-gl.js")
check("vendored MapLibre served", s == 200 and len(b) > 500000)
s, b = call("/api/call", {"text": "face drooping on one side", "lat": 37.33, "lon": -121.93})
check("AI path blocked by the cap (429, no Bedrock call)", s == 429, b[:90])
if calls:
    ms = []
    for _ in range(calls):
        t0 = time.perf_counter()
        s, _b = call("/api/recommend", {"lat": 37.33, "lon": -121.93, "incident_type": "stroke"})
        ms.append((time.perf_counter() - t0) * 1000)
        ok &= s == 200
    ms.sort()
    print(f"{calls} recommend calls: p50 {ms[len(ms)//2]:.0f} ms, p95 {ms[int(len(ms)*0.95)-1]:.0f} ms")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
