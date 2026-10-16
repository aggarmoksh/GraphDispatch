"""Before/after numbers for the demo closure on S1 (graph only, against a sjfd_test server): python docs/phases/phase9/before_after.py http://localhost:8001"""
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")


def call(method, path, body=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))


assert call("GET", "/api/health")["graph"] == "sjfd_test"
for c in call("GET", "/api/closures")["closures"]:
    call("DELETE", "/api/closures/" + c["closure_id"])
S1 = {"lat": 37.33, "lon": -121.93, "incident_type": "stroke"}


def show(tag, d):
    units = ", ".join(f"{u['unit_id']} {u['eta_s']:.1f} s" for u in d["units"])
    h = d["destination"]
    print(f"{tag}: units {units}; hospital {h['name']} {h['eta_s']:.1f} s; rerouted {[(x['leg'], x['name'], x['extra_s']) for x in d['rerouted']]}; "
          f"changes {[(c['capability'], c['without'], c['with']) for c in d['changes']['units']]}; no_route {d['no_route']}")


show("BEFORE (no closures)", call("POST", "/api/recommend", S1))
ids = []
for r in call("GET", "/api/meta")["demo_closures"]:
    out = call("POST", "/api/closures", {"src_osm": r["src_osm"], "dst_osm": r["dst_osm"], "reason": r["reason"]})
    ids.append(out["closure"]["closure_id"])
    print("closed:", r["role"], r["name"], r["src_osm"], r["dst_osm"])
show("AFTER  (both demo closures)", call("POST", "/api/recommend", S1))
for i in ids:
    call("DELETE", "/api/closures/" + i)
show("REOPENED", call("POST", "/api/recommend", S1))
