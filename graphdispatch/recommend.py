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


def fmt_reason(reason):
    """'base' -> 'required by incident type'; 'hazard:<id>:<kind>' -> 'added by <kind>'."""
    out = []
    for part in str(reason).split(", "):
        out.append("required by incident type" if part == "base" else f"added by {part.split(':')[-1]}")
    return ", ".join(out)


def _eta(src, dst, timings, cache, query="eta"):
    key = (src, dst)
    if key not in cache:
        if src == dst:
            cache[key] = 0.0
        else:
            rows = db.read(query, {"src": src, "dst": dst}, timings)
            cache[key] = float(rows[0][0]) if rows else None
    return cache[key]


def _route(src, dst, timings):
    if src == dst:
        return [src]
    rows = db.read("route", {"src": src, "dst": dst}, timings)
    return list(rows[0][1]) if rows else []


def _assign(cands, needs, sources):
    """Scarcest capability first (fewest candidate units), so shared units are not wasted; ties by name; a unit counted once."""
    used, chosen, unmet = set(), [], []
    for cap in sorted(needs, key=lambda c: (len(cands.get(c, [])), c)):
        picked = 0
        reason = ", ".join(sources[cap])
        for eta, unit_id, station_id in sorted(cands.get(cap, [])):
            if picked == needs[cap]:
                break
            if unit_id in used:
                continue
            used.add(unit_id)
            chosen.append({"unit_id": unit_id, "capability": cap, "station_id": station_id, "eta_s": eta, "reason": reason})
            picked += 1
        if picked < needs[cap]:
            unmet.append({"capability": cap, "missing": needs[cap] - picked, "reason": reason})
    chosen.sort(key=lambda u: (u["eta_s"], u["unit_id"]))
    return chosen, unmet


def _pick_hospital(hosp, dest_cap, fb_cap, max_extra, max_total, source):
    """hosp: list of {osm_id, name, eta_s, capabilities, level}. Returns (best, rule_applied, capable, nearest) after sorting."""
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
    return best, rule_applied, capable, nearest


def recommend(lat, lon, incident_type, incident_id=None, now=None):
    """Rank units and pick a hospital. With incident_id, requirements include those added by active hazards.

    Routing uses relTypes ['ROAD'], so closed roads (CLOSED_ROAD) are skipped. When closures are active the same decision is
    also computed ignoring them, to record which legs were rerouted (and by how much) and what would have changed.
    """
    t_start = time.perf_counter()
    timings = []
    cache, cache_free = {}, {}
    node, snap_m = snap(lat, lon, timings)
    closures_active = db.read("active_closure_count", None, timings)[0][0] > 0

    if incident_id:
        now = int(time.time()) if now is None else int(now)
        rows = db.read("effective_requirements", {"incident_id": incident_id, "now": now}, timings)
        needs = {r[0]: int(r[1]) for r in rows}
        sources = {r[0]: list(r[2]) for r in rows}
    else:
        needs = {r[0]: r[1] for r in db.read("required_caps", {"name": incident_type}, timings)}
        sources = {c: ["base"] for c in needs}
    if not needs:
        raise ValueError(f"unknown incident type: {incident_type}")
    cands, cands_free, st_node, unreachable = {}, {}, {}, []
    for cap, unit_id, station_id, n in db.read("unit_candidates", {"caps": sorted(needs)}, timings):
        eta = _eta(n, node, timings, cache)
        if closures_active:
            eta_free = _eta(n, node, timings, cache_free, "eta_all")
            if eta_free is not None:
                cands_free.setdefault(cap, []).append((eta_free, unit_id, station_id))
        if eta is not None:
            cands.setdefault(cap, []).append((eta, unit_id, station_id))
            st_node[unit_id] = n
        elif unit_id not in unreachable:
            unreachable.append(unit_id)

    considered = []
    for cap in sorted(cands):
        for rank, (eta, unit_id, station_id) in enumerate(sorted(cands[cap])[:TOP_N], 1):
            considered.append({"unit_id": unit_id, "capability": cap, "eta_s": eta, "rank": rank})

    chosen, unmet = _assign(cands, needs, sources)
    routes = [{"leg": u["unit_id"], "nodes": _route(st_node[u["unit_id"]], node, timings)} for u in chosen]

    hospital, rule_applied = None, f"no destination hospital required for {incident_type}"
    dest = db.read("dest_capability", {"name": incident_type}, timings)
    hosp_rows, hosp_free, h_node = [], [], {}
    best_free = None
    if dest:
        dest_cap, fb_cap, max_extra, max_total, source = dest[0]
        hosp = []
        for osm_id, name, hn, caps, offers in db.read("hospitals", None, timings):
            levels = {o["cap"]: o["level"] for o in offers if o.get("cap") and o.get("level")}
            h = {"osm_id": osm_id, "name": name, "capabilities": sorted(caps), "level": levels.get(dest_cap)}
            eta = _eta(node, hn, timings, cache)
            if closures_active:
                eta_free = _eta(node, hn, timings, cache_free, "eta_all")
                if eta_free is not None:
                    hosp_free.append({**h, "eta_s": eta_free})
            if eta is not None:
                hosp.append({**h, "eta_s": eta})
                h_node[osm_id] = hn
            else:
                hosp_rows.append(name)
        best, rule_applied, capable, nearest = _pick_hospital(hosp, dest_cap, fb_cap, max_extra, max_total, source)
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
        if closures_active and hosp_free:
            best_free = _pick_hospital(hosp_free, dest_cap, fb_cap, max_extra, max_total, source)[0]

    rerouted, changes, no_route = [], {"units": [], "hospital": None}, []
    if closures_active:
        # which legs had to route around a closure, and what each detour cost
        for u in chosen:
            rerouted += _rerouted_leg(u["unit_id"], st_node[u["unit_id"]], node, u["eta_s"], timings)
        if hospital and hospital["chosen"]:
            rerouted += _rerouted_leg("hospital", node, h_node[hospital["chosen"]["osm_id"]], hospital["chosen"]["eta_s"], timings)
        # what would have been chosen without the closures
        free_chosen, _ = _assign(cands_free, needs, sources)
        for cap in sorted(needs):
            now_ids = sorted(u["unit_id"] for u in chosen if u["capability"] == cap)
            free_ids = sorted(u["unit_id"] for u in free_chosen if u["capability"] == cap)
            if now_ids != free_ids:
                changes["units"].append({"capability": cap, "without": free_ids, "with": now_ids,
                                         "without_eta": [round(u["eta_s"], 1) for u in free_chosen if u["capability"] == cap],
                                         "with_eta": [round(u["eta_s"], 1) for u in chosen if u["capability"] == cap]})
        chosen_h = hospital["chosen"] if hospital else None
        if best_free and (chosen_h is None or best_free["osm_id"] != chosen_h["osm_id"]):
            changes["hospital"] = {"without": best_free["name"], "without_eta": round(best_free["eta_s"], 1),
                                   "with": chosen_h["name"] if chosen_h else None, "with_eta": round(chosen_h["eta_s"], 1) if chosen_h else None}
        no_route = list(unreachable)[:8]
        if dest and hospital and hospital["chosen"] is None and hosp_free:
            no_route.append("hospital")

    by_query = {}
    for name, ms in timings:
        by_query[name] = by_query.get(name, 0.0) + ms
    return {
        "incident": {"lat": lat, "lon": lon, "type": incident_type, "node": node, "snap_m": snap_m, "synthetic_type": True},
        "requirements": {c: {"need": needs[c], "sources": sources[c]} for c in sorted(needs)},
        "units": chosen, "considered": considered, "unmet": unmet, "hospital": hospital,
        "rule_applied": rule_applied, "routes": routes,
        "closures_active": closures_active, "rerouted": rerouted, "changes": changes, "no_route": no_route,
        "timings_ms": {"by_query": by_query, "total": (time.perf_counter() - t_start) * 1000},
        "queries_used": sorted(by_query),
    }


def _rerouted_leg(leg, src, dst, real_eta, timings):
    """If the cheapest path over ROAD and CLOSED_ROAD passes a closed road, return one row per closure with the extra seconds."""
    if src == dst:
        return []
    rows = db.read("route_all", {"src": src, "dst": dst}, timings)
    if not rows:
        return []
    weight, _nodes, closed = rows[0]
    extra = real_eta - float(weight)
    if not closed or extra <= 0.01:
        return []
    return [{"leg": leg, "closure_id": cid, "extra_s": round(extra, 1)} for cid in dict.fromkeys(closed)]


def hospital_label(h):
    """Hospital name with its designation level for the needed capability, when present."""
    return f"{h['name']} (level {h['level']})" if h.get("level") else h["name"]


def explain(r):
    lines = [f"Incident {r['incident']['type']} (synthetic type) at ({r['incident']['lat']}, {r['incident']['lon']}), "
             f"snapped {r['incident']['snap_m']:.0f} m to intersection {r['incident']['node']}"]
    lines.append("Units (synthetic):")
    for u in r["units"]:
        lines.append(f"  {u['unit_id']:5} covers {u['capability']:17} from station {u['station_id']:>2}  ETA {u['eta_s']:.0f} s"
                     f"  [{fmt_reason(u['reason'])}]")
    for m in r["unmet"]:
        lines.append(f"  UNMET: {m['capability']} ({fmt_reason(m['reason'])})")
    h = r["hospital"]
    if h:
        c, n = h["chosen"], h["nearest"]
        lines.append(f"Hospital needs {h['required_capability']}: " + (f"{hospital_label(c)} (ETA {c['eta_s']:.0f} s)" if c else "none available"))
        if n:
            lines.append(f"  Nearest of any kind: {n['name']} (ETA {n['eta_s']:.0f} s)")
        if h["skipped_reason"]:
            lines.append(f"  Skipped: {h['skipped_reason']}")
    for x in r.get("rerouted", []):
        lines.append(f"Rerouted around a closed road for {x['leg']}: +{x['extra_s']:.0f} s (closure {x['closure_id']})")
    for ch in r.get("changes", {}).get("units", []):
        lines.append(f"Without the closure, {', '.join(ch['without'])} would have covered {ch['capability']}")
    if r.get("changes", {}).get("hospital"):
        lines.append(f"Without the closure the patient would have gone to {r['changes']['hospital']['without']}")
    for leg in r.get("no_route", []):
        lines.append(f"No route: {leg}")
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
