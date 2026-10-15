"""Deterministic unit ranking and hospital choice, purely from Cypher queries (no oracle imports)."""
import argparse
import time

from . import db

MAX_SNAP_M = 500.0


class OutOfArea(Exception):
    """Incident is more than MAX_SNAP_M from any mapped intersection."""


def _eta(src, dst, timings, cache):
    key = (src, dst)
    if key not in cache:
        if src == dst:
            cache[key] = 0.0
        else:
            rows = db.run("eta", {"src": src, "dst": dst}, timings)
            cache[key] = float(rows[0][0]) if rows else None
    return cache[key]


def recommend(lat, lon, incident_type):
    t_start = time.perf_counter()
    timings = []
    cache = {}

    snap = db.run("snap_incident", {"lat": float(lat), "lon": float(lon)}, timings)[0]
    node, snap_m = snap[0], float(snap[1])
    if snap_m > MAX_SNAP_M:
        raise OutOfArea(f"incident is {snap_m:.0f} m from the nearest mapped intersection (limit {MAX_SNAP_M:.0f} m)")

    needs = {r[0]: r[1] for r in db.run("required_caps", {"name": incident_type}, timings)}
    if not needs:
        raise ValueError(f"unknown incident type: {incident_type}")
    cands = {}
    for cap, need, unit_id, station_id, st_node in db.run("unit_candidates", {"name": incident_type}, timings):
        eta = _eta(st_node, node, timings, cache)
        if eta is not None:
            cands.setdefault(cap, []).append((eta, unit_id, station_id))

    # Scarcest capability first (fewest candidate units), so shared units are not wasted; ties by name.
    used, chosen, unmet = set(), [], []
    for cap in sorted(needs, key=lambda c: (len(cands.get(c, [])), c)):
        picked = 0
        for eta, unit_id, station_id in sorted(cands.get(cap, [])):
            if picked == needs[cap]:
                break
            if unit_id in used:
                continue
            used.add(unit_id)
            chosen.append({"unit_id": unit_id, "capability": cap, "station_id": station_id, "eta_s": eta})
            picked += 1
        if picked < needs[cap]:
            unmet.append({"capability": cap, "missing": needs[cap] - picked})
    chosen.sort(key=lambda u: (u["eta_s"], u["unit_id"]))

    hospital = None
    dest = db.run("dest_capability", {"name": incident_type}, timings)
    if dest:
        dest_cap = dest[0][0]
        hosp = []
        for osm_id, name, h_node, caps in db.run("hospitals", None, timings):
            eta = _eta(node, h_node, timings, cache)
            if eta is not None:
                hosp.append({"osm_id": osm_id, "name": name, "eta_s": eta, "capabilities": sorted(caps)})
        hosp.sort(key=lambda h: (h["eta_s"], h["osm_id"]))
        ok = [h for h in hosp if dest_cap in h["capabilities"]]
        nearest = hosp[0] if hosp else None
        best = ok[0] if ok else None
        reason = None
        if nearest and best and nearest["osm_id"] != best["osm_id"]:
            reason = f"{nearest['name']} is nearest ({nearest['eta_s']:.0f} s) but lacks {dest_cap}"
        elif nearest and not best:
            reason = f"no hospital offers {dest_cap}"
        hospital = {"required_capability": dest_cap, "chosen": best, "nearest": nearest,
                    "differs_from_nearest": bool(best and nearest and best["osm_id"] != nearest["osm_id"]),
                    "skipped_reason": reason}

    by_query = {}
    for name, ms in timings:
        by_query[name] = by_query.get(name, 0.0) + ms
    return {
        "incident": {"lat": lat, "lon": lon, "type": incident_type, "node": node, "snap_m": snap_m, "synthetic_type": True},
        "units": chosen, "unmet": unmet, "hospital": hospital,
        "timings_ms": {"by_query": by_query, "total": (time.perf_counter() - t_start) * 1000},
        "queries_used": sorted(by_query),
    }


def explain(r):
    lines = [f"Incident {r['incident']['type']} (synthetic type) at ({r['incident']['lat']}, {r['incident']['lon']}), "
             f"snapped {r['incident']['snap_m']:.0f} m to intersection {r['incident']['node']}"]
    lines.append("Units (synthetic):")
    for u in r["units"]:
        lines.append(f"  {u['unit_id']:5} covers {u['capability']:17} from station {u['station_id']:>2}  ETA {u['eta_s']:.0f} s")
    for m in r["unmet"]:
        lines.append(f"  UNMET: {m['capability']} short by {m['missing']}")
    h = r["hospital"]
    if h:
        c, n = h["chosen"], h["nearest"]
        lines.append(f"Hospital needs {h['required_capability']}: " + (f"{c['name']} (ETA {c['eta_s']:.0f} s)" if c else "none available"))
        if n:
            lines.append(f"  Nearest of any kind: {n['name']} (ETA {n['eta_s']:.0f} s)")
        if h["skipped_reason"]:
            lines.append(f"  Skipped: {h['skipped_reason']}")
    lines.append(f"Total {r['timings_ms']['total']:.1f} ms; queries: {', '.join(r['queries_used'])}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(prog="python -m graphdispatch.recommend")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--type", required=True, dest="incident_type")
    a = ap.parse_args()
    try:
        print(explain(recommend(a.lat, a.lon, a.incident_type)))
    except OutOfArea as e:
        print("OUT OF AREA:", e)


if __name__ == "__main__":
    main()
