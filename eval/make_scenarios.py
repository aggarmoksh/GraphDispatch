"""Generate eval/scenarios.json (24 scenarios). Deterministic: random.Random(42). Run once; the output is committed.

Sampling rule for the 17 random points: uniform inside box B2, rejected unless the nearest routable intersection is within
300 m (haversine) AND the second nearest is at least 1 m farther (so snapping cannot be ambiguous between implementations).
Incident types cycle through all 7. The two "nearest needed unit is busy" scenarios mark the oracle's fastest chosen unit
(computed with every unit available) as busy.
"""
import json
import random
from pathlib import Path

import oracle

OUT = Path(__file__).resolve().parent / "scenarios.json"
B2 = {"west": -121.945, "south": 37.300, "east": -121.840, "north": 37.370}
TYPES = ["structure_fire", "cardiac_arrest", "stroke", "major_trauma", "pediatric_trauma", "burn", "hazmat_spill"]


def base(sid, name, itype, lat, lon, **kw):
    return {"id": sid, "name": name, "incident_type": itype, "lat": lat, "lon": lon, "address": kw.pop("address", f"eval {sid}"),
            "hazards": kw.pop("hazards", []), "prior_incidents": kw.pop("prior_incidents", []),
            "busy_units": kw.pop("busy_units", []), "after": kw.pop("after", None)}


def main():
    w = oracle.World()
    sc = [
        base("S1", "stroke, west side", "stroke", 37.3300, -121.9300),
        base("S2", "burn, east side", "burn", 37.3600, -121.8550),
        base("S3", "pediatric trauma", "pediatric_trauma", 37.3100, -121.8600),
        base("S4", "hazmat spill", "hazmat_spill", 37.3200, -121.9100),
        base("S5", "structure fire, nearest needed unit busy", "structure_fire", 37.3450, -121.8800),
        base("O1", "garage fire with oxygen stored at the address", "structure_fire", 37.3360, -121.8900,
             address="200 Demo St", hazards=["oxygen_storage"]),
        base("O2", "collapse next door, same address, remembers O1", "cardiac_arrest", 37.3360, -121.8900,
             address="200 Demo St", hazards=["oxygen_storage"], prior_incidents=["structure_fire"], after="O1"),
    ]
    rng = random.Random(42)
    i = 0
    while i < 17:
        lat = round(rng.uniform(B2["south"], B2["north"]), 5)
        lon = round(rng.uniform(B2["west"], B2["east"]), 5)
        near = w.nearest(lat, lon, 2)
        if near[0][0] > 300 or near[1][0] - near[0][0] < 1.0:
            continue
        i += 1
        t = TYPES[(i - 1) % 7]
        sc.append(base(f"R{i:02d}", f"random point {i}, {t.replace('_', ' ')}", t, lat, lon))

    # two scenarios whose nearest needed unit is busy (the oracle's fastest chosen unit, with everyone available)
    targets = [s for s in sc if s["id"] == "S5"] + [next(s for s in sc if s["id"].startswith("R") and s["incident_type"] == "cardiac_arrest")]
    for s in targets:
        first = oracle.solve(s, w)["units"][0]["unit_id"]
        s["busy_units"] = [first]
        s["name"] += "" if s["id"] == "S5" else ", nearest needed unit busy"
    OUT.write_text(json.dumps({"seed": 42, "box": B2, "scenarios": sc}, indent=1), encoding="utf-8")
    print(len(sc), "scenarios written")
    for s in sc:
        print(s["id"], s["incident_type"], s["lat"], s["lon"], s["busy_units"], s["hazards"], s["prior_incidents"])


if __name__ == "__main__":
    main()
