"""Configuration B: straight-line baseline (see eval/PROTOCOL.md section 5). Standard library only.

Same assignment procedure as the oracle, but time = haversine distance / 13.4 m/s, base requirements only (no hazard
knowledge, no address memory). Frozen by the commit that contains eval/PROTOCOL.md.
"""
import oracle

SPEED_MPS = 13.4


def solve(scenario, world=None):
    w = world or oracle.WORLD()
    t = w.types[scenario["incident_type"]]
    lat, lon = scenario["lat"], scenario["lon"]
    status = oracle._status(w, scenario.get("busy_units", []))

    def unit_time(u):
        slat, slon = w.stations[w.units[u]["station_id"]]
        return oracle.haversine(slat, slon, lat, lon) / SPEED_MPS

    need = dict(t["requires"])
    cands = {c: sorted((unit_time(u), u) for u, d in w.units.items() if c in d["capabilities"] and status[u] == "available") for c in need}
    used, chosen = set(), []
    for cap in sorted(need, key=lambda c: (len(cands[c]), c)):
        picked = 0
        for e, u in cands[cap]:
            if picked == need[cap]:
                break
            if u in used:
                continue
            used.add(u)
            chosen.append({"unit_id": u, "capability": cap, "eta_s": e})
            picked += 1
    chosen.sort(key=lambda x: (x["eta_s"], x["unit_id"]))

    hospital = None
    if t["destination"]:
        hs = sorted(((oracle.haversine(h["lat"], h["lon"], lat, lon) / SPEED_MPS, h["osm_id"], h) for h in w.hospitals), key=lambda x: (x[0], x[1]))
        capable = next(((e, h) for e, _, h in hs if t["destination"] in h["capabilities"]), None)
        if t["fallback"]:
            fb = next(((e, h) for e, _, h in hs if t["fallback"] in h["capabilities"]), None)
            if capable is None:
                pick = fb
            elif fb is None:
                pick = capable
            else:
                pick = capable if (capable[0] - fb[0] <= t["max_extra_s"] and capable[0] <= t["max_total_s"]) else fb
        else:
            pick = capable
        if pick:
            hospital = {"osm_id": pick[1]["osm_id"], "name": pick[1]["name"], "eta_s": pick[0]}
    return {"units": chosen, "hospital": hospital, "recall": {"hazards": [], "prior_incident_types": []}}
