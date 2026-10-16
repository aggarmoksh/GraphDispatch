"""Deterministic unit ranking and hospital choice, purely from Cypher queries (no oracle imports). Read-only."""
import argparse
import time

from . import db
from .rules import stroke_bypass

MAX_SNAP_M = 500.0
TOP_N = 5


class OutOfArea(Exception):
    """Incident is more than MAX_SNAP_M from any mapped intersection."""


def snap(lat, lon, timings=None):
    """Return (intersection osm_id, snap distance m); raise OutOfArea beyond MAX_SNAP_M."""
    node, snap_m = db.read("snap_incident", {"lat": float(lat), "lon": float(lon)}, timings)[0]
    if snap_m > MAX_SNAP_M:
        raise OutOfArea(f"incident is {snap_m:.0f} m from the nearest mapped intersection (limit {MAX_SNAP_M:.0f} m)")
    return node, float(snap_m)


def _eta(src, dst, timings, cache):
    key = (src, dst)
    if key not in cache:
        if src == dst:
            cache[key] = 0.0
        else:
            rows = db.read("eta", {"src": src, "dst": dst}, timings)
            cache[key] = float(rows[0][0]) if rows else None
    return cache[key]


def _route(src, dst, timings):
    if src == dst:
        return [src]
    rows = db.read("route", {"src": src, "dst": dst}, timings)
    return list(rows[0][1]) if rows else []


def recommend(lat, lon, incident_type):
    t_start = time.perf_counter()
    timings = []
    cache = {}
    node, snap_m = snap(lat, lon, timings)

    needs = {r[0]: r[1] for r in db.read("required_caps", {"name": incident_type}, timings)}
    if not needs:
        raise ValueError(f"unknown incident type: {incident_type}")
    cands, st_node = {}, {}
    for cap, need, unit_id, station_id, n in db.read("unit_candidates", {"name": incident_type}, timings):
        eta = _eta(n, node, timings, cache)
        if eta is not None:
            cands.setdefault(cap, []).append((eta, unit_id, station_id))
            st_node[unit_id] = n

    considered = []
    for cap in sorted(cands):
        for rank, (eta, unit_id, station_id) in enumerate(sorted(cands[cap])[:TOP_N], 1):
            considered.append({"unit_id": unit_id, "capability": cap, "eta_s": eta, "rank": rank})

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

    routes = [{"leg": u["unit_id"], "nodes": _route(st_node[u["unit_id"]], node, timings)} for u in chosen]

    hospital, rule_applied = None, f"no destination hospital required for {incident_type}"
    dest = db.read("dest_capability", {"name": incident_type}, timings)
    if dest:
        dest_cap, fb_cap, max_extra, max_total, source = dest[0]
        hosp, h_node = [], {}
        for osm_id, name, hn, caps in db.read("hospitals", None, timings):
            eta = _eta(node, hn, timings, cache)
            if eta is not None:
                hosp.append({"osm_id": osm_id, "name": name, "eta_s": eta, "capabilities": sorted(caps)})
                h_node[osm_id] = hn
        hosp.sort(key=lambda h: (h["eta_s"], h["osm_id"]))
        nearest = hosp[0] if hosp else None
        capable = next((h for h in hosp if dest_cap in h["capabilities"]), None)
        if fb_cap:
            fallback = next((h for h in hosp if fb_cap in h["capabilities"]), None)
            best, rule_applied, _ = stroke_bypass(capable, fallback, max_extra, max_total, source or "rule")
        else:
            best = capable
            rule_applied = (f"fastest hospital offering {dest_cap}: {best['name']} ({best['eta_s']:.0f} s)" if best
                            else f"no hospital offers {dest_cap}")
        skipped = []
        for h in hosp:
            if best and h["eta_s"] >= best["eta_s"]:
                break
            if h is best:
                continue
            if dest_cap not in h["capabilities"]:
                reason = f"{h['name']} lacks {dest_cap}" + (" (nearest)" if h is nearest else "")
            else:
                reason = rule_applied
            skipped.append({"osm_id": h["osm_id"], "name": h["name"], "eta_s": h["eta_s"], "reason": reason})
        if best and capable and best is not capable:  # rule sent us to the fallback
            skipped.append({"osm_id": capable["osm_id"], "name": capable["name"], "eta_s": capable["eta_s"], "reason": rule_applied})
        reason = None
        if nearest and best and nearest["osm_id"] != best["osm_id"]:
            if dest_cap in nearest["capabilities"]:
                reason = rule_applied
            else:
                reason = f"{nearest['name']} is nearest ({nearest['eta_s']:.0f} s) but lacks {dest_cap}"
        elif nearest and not best:
            reason = f"no hospital offers {dest_cap}"
        hospital = {"required_capability": dest_cap, "chosen": best, "nearest": nearest,
                    "differs_from_nearest": bool(best and nearest and best["osm_id"] != nearest["osm_id"]),
                    "skipped_reason": reason, "skipped": skipped}
        if best:
            routes.append({"leg": "hospital", "nodes": _route(node, h_node[best["osm_id"]], timings)})

    by_query = {}
    for name, ms in timings:
        by_query[name] = by_query.get(name, 0.0) + ms
    return {
        "incident": {"lat": lat, "lon": lon, "type": incident_type, "node": node, "snap_m": snap_m, "synthetic_type": True},
        "units": chosen, "considered": considered, "unmet": unmet, "hospital": hospital,
        "rule_applied": rule_applied, "routes": routes,
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
    lines.append(f"Rule: {r['rule_applied']}")
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
