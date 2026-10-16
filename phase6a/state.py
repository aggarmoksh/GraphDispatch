"""Print a compact fingerprint of a running stack's graph: node/relationship totals and open incident count."""
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
get = lambda p: json.load(urllib.request.urlopen(base + p, timeout=20))  # noqa: E731
meta, inc = get("/api/meta"), get("/api/incidents")
n, r = meta["counts"]["nodes"], meta["counts"]["relationships"]
print(json.dumps({"graph": meta["graph"], "nodes_total": sum(n.values()), "rels_total": sum(r.values()),
                  "Intersection": n.get("Intersection"), "ROAD": r.get("ROAD"), "Incident": n.get("Incident", 0),
                  "Decision": n.get("Decision", 0), "open_incidents": len(inc["incidents"])}))
