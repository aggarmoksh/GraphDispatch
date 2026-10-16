"""Incident memory, decision provenance and the human-confirmed dispatch action. All synthetic IDs."""
import csv
import re
import time
import uuid
from pathlib import Path

from . import db
from .recommend import fmt_reason, hospital_label, recommend, snap

RECALL_WINDOW_S = 30 * 86400
HAZARD_WINDOW_S = 30 * 86400


class UnknownHazardKind(Exception):
    """add_hazard was given a kind that is not a HazardKind."""


class DispatchRefused(Exception):
    """A chosen unit is no longer available (or the decision has no chosen units); nothing was changed."""


_SUFFIXES = None


def _suffixes():
    global _SUFFIXES
    if _SUFFIXES is None:
        path = Path(__file__).resolve().parent.parent / "seed" / "address_suffixes.csv"
        with path.open(newline="", encoding="utf-8") as f:
            _SUFFIXES = {r["word"]: r["abbr"] for r in csv.DictReader(f)}
    return _SUFFIXES


def address_id(label):
    """Lowercase, strip punctuation, collapse whitespace, abbreviate the last word via seed/address_suffixes.csv.

    Device-derived labels ("device@lat,lon") are kept as typed (lowercased).
    """
    text = label.strip().lower()
    if text.startswith("device@"):
        return text
    words = re.sub(r"[^a-z0-9 ]+", " ", text).split()
    if words:
        words[-1] = _suffixes().get(words[-1], words[-1])
    return " ".join(words)


def _new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def create_incident(caller_id, address_label, lat, lon, type, now=None, call_text=None, intake_model=None):
    now = int(time.time()) if now is None else int(now)
    node, _ = snap(lat, lon)  # raises OutOfArea before anything is written
    incident_id = _new_id("inc")
    db.write("create_incident", {"caller_id": caller_id, "address_id": address_id(address_label), "label": address_label,
                                 "lat": float(lat), "lon": float(lon), "type": type, "node": node,
                                 "incident_id": incident_id, "now": now,
                                 "call_text": call_text, "intake_model": intake_model, "created_ns": time.time_ns()})
    return incident_id


def recall(incident_id, now=None):
    """Prior incidents at the same address in the last 30 days, and hazards valid now."""
    now = int(time.time()) if now is None else int(now)
    inc = [dict(incident_id=r[0], type=r[1], created_at=r[2], status=r[3])
           for r in db.read("recall_incidents", {"incident_id": incident_id, "since": now - RECALL_WINDOW_S})]
    haz = [dict(hazard_id=r[0], kind=r[1], note=r[2], valid_from=r[3], valid_to=r[4], crew_note=r[5], reported_by=r[6])
           for r in db.read("recall_hazards", {"incident_id": incident_id, "now": now})]
    return {"incidents": inc, "hazards": haz, "hazard_groups": group_hazards(haz)}


def group_hazards(hazards):
    """Group hazards by kind: [{kind, count, notes, crew_note, hazard_ids}]."""
    groups = {}
    for h in hazards:
        g = groups.setdefault(h["kind"], {"kind": h["kind"], "count": 0, "notes": [], "crew_note": h.get("crew_note"),
                                          "hazard_ids": []})
        g["count"] += 1
        g["notes"].append(h.get("note"))
        g["hazard_ids"].append(h["hazard_id"])
    return list(groups.values())


def format_group(g):
    head = f"{g['kind']} x{g['count']}" if g["count"] > 1 else g["kind"]
    return f"{head}: " + "; ".join(n for n in g["notes"] if n)


def add_hazard(address_label, kind, note, valid_from, valid_to, incident_id=None, now=None, reported_by=None,
               lat=None, lon=None):
    now = int(time.time()) if now is None else int(now)
    allowed = [r[0] for r in db.read("hazard_kinds")]
    if kind not in allowed:
        raise UnknownHazardKind(f"unknown hazard kind {kind!r}; allowed kinds: {', '.join(allowed)}")
    hazard_id = _new_id("haz")
    db.write("add_hazard", {"address_id": address_id(address_label), "label": address_label, "hazard_id": hazard_id,
                            "kind": kind, "note": note, "valid_from": int(valid_from), "valid_to": int(valid_to), "now": now,
                            "reported_by": reported_by, "created_ns": time.time_ns(),
                            "lat": None if lat is None else float(lat), "lon": None if lon is None else float(lon)})
    if incident_id:
        db.write("hazard_reported_in", {"hazard_id": hazard_id, "incident_id": incident_id})
    return hazard_id


def record_decision(incident_id, rec, recalled=None, now=None):
    now = int(time.time()) if now is None else int(now)
    recalled = recalled or {"incidents": [], "hazards": []}
    did = _new_id("dec")
    p = {"decision_id": did}
    db.write("decision_create", {**p, "incident_id": incident_id, "ts": now, "rule_applied": rec["rule_applied"],
                                    "unmet": [m["capability"] for m in rec["unmet"]],
                                    "unmet_reasons": [m["reason"] for m in rec["unmet"]]})
    if rec["considered"]:
        db.write("decision_considered", {**p, "rows": rec["considered"]})
    if rec["units"]:
        db.write("decision_chose", {**p, "rows": [{k: u[k] for k in ("unit_id", "capability", "eta_s", "reason")} for u in rec["units"]]})
    h = rec["hospital"]
    if h and h["chosen"]:
        db.write("decision_destination", {**p, "osm_id": h["chosen"]["osm_id"], "eta_s": h["chosen"]["eta_s"], "level": h["chosen"].get("level")})
    if h and h["skipped"]:
        db.write("decision_skipped", {**p, "rows": [{k: s[k] for k in ("osm_id", "eta_s", "reason")} for s in h["skipped"]]})
    route = [{"leg": r["leg"], "seq": i, "node": n} for r in rec["routes"] for i, n in enumerate(r["nodes"])]
    if route:
        db.write("decision_route", {**p, "rows": route})
    if recalled["hazards"]:
        db.write("decision_recalled_hazards", {**p, "ids": [x["hazard_id"] for x in recalled["hazards"]]})
    if recalled["incidents"]:
        db.write("decision_recalled_incidents", {**p, "ids": [x["incident_id"] for x in recalled["incidents"]]})
    return did


def why(decision_id):
    """Everything recorded for a decision, from ONE read-only Cypher query."""
    rows = db.read("why", {"decision_id": decision_id})
    if not rows:
        raise KeyError(decision_id)
    (did, ts, agent, rule, inc_id, itype, status, address, considered, chose, dest, skipped, route, rhaz, rinc,
     unmet, unmet_reasons) = rows[0]

    def keep(items, key):
        return [x for x in items if x.get(key) is not None]

    return {
        "decision_id": did, "ts": ts, "agent": agent, "rule_applied": rule,
        "incident": {"incident_id": inc_id, "type": itype, "status": status, "address": address},
        "considered": sorted(keep(considered, "unit_id"), key=lambda x: (x["capability"], x["rank"])),
        "chose": sorted(keep(chose, "unit_id"), key=lambda x: (x["eta_s"], x["unit_id"])),
        "destination": (keep(dest, "osm_id") or [None])[0],
        "skipped": sorted(keep(skipped, "osm_id"), key=lambda x: x["eta_s"]),
        "route": sorted(keep(route, "leg"), key=lambda x: (x["leg"], x["seq"])),
        "recalled_hazards": sorted(keep(rhaz, "hazard_id"), key=lambda h: (h.get("created_ns") or 0, h["hazard_id"])),
        "recalled_incidents": keep(rinc, "incident_id"),
        "unmet": [{"capability": c, "reason": r} for c, r in zip(unmet or [], unmet_reasons or [])],
    }


def dispatch(decision_id):
    """Assign the chosen units and mark the incident dispatched, all in one query or not at all."""
    rows = db.write("dispatch", {"decision_id": decision_id})
    if not rows:
        units = db.read("decision_units", {"decision_id": decision_id})
        if not units:
            raise DispatchRefused(f"decision {decision_id} has no chosen units")
        bad = [u for u, s in units if s != "available"]
        raise DispatchRefused(f"unit(s) no longer available: {', '.join(bad)}; nothing changed")
    return rows[0][0]


def clear(incident_id):
    return db.write("clear", {"incident_id": incident_id})[0][0]


def run_call(caller_id, address_label, lat, lon, type, now=None):
    """Create incident, recall memory, recommend, record the decision. Does NOT dispatch."""
    now = int(time.time()) if now is None else int(now)
    incident_id = create_incident(caller_id, address_label, lat, lon, type, now)
    return decide(incident_id, lat, lon, type, now)


def decide(incident_id, lat, lon, type, now):
    """Recall memory, recommend (with hazard-added requirements), record the decision. Does NOT dispatch."""
    recalled = recall(incident_id, now)
    rec = recommend(lat, lon, type, incident_id=incident_id, now=now)
    decision_id = record_decision(incident_id, rec, recalled, now)
    return {"incident_id": incident_id, "decision_id": decision_id, "recalled": recalled, "recommendation": rec}


def explain_why(w):
    lines = [f"Decision {w['decision_id']} ({w['agent']}) for incident {w['incident']['incident_id']} "
             f"[{w['incident']['type']}, synthetic] at {w['incident']['address']}, status {w['incident']['status']}",
             f"Rule: {w['rule_applied']}", "Chosen units (synthetic):"]
    for u in w["chose"]:
        lines.append(f"  {u['unit_id']:5} covers {u['capability']:17} ETA {u['eta_s']:.0f} s  [{fmt_reason(u['reason'])}]")
    for m in w["unmet"]:
        lines.append(f"  UNMET: {m['capability']} ({fmt_reason(m['reason'])})")
    for cap in sorted({c["capability"] for c in w["considered"]}):
        cs = [f"{c['unit_id']} {c['eta_s']:.0f}s" for c in w["considered"] if c["capability"] == cap]
        lines.append(f"  considered for {cap}: " + ", ".join(cs))
    if w["destination"]:
        lines.append(f"Destination: {hospital_label(w['destination'])} (ETA {w['destination']['eta_s']:.0f} s)")
    for s in w["skipped"]:
        lines.append(f"  skipped {s['name']} ({s['eta_s']:.0f} s): {s['reason']}")
    legs = {}
    for r in w["route"]:
        legs[r["leg"]] = legs.get(r["leg"], 0) + 1
    lines.append("Route legs (intersections): " + ", ".join(f"{k}={v}" for k, v in sorted(legs.items())))
    for g in group_hazards(w["recalled_hazards"]):
        lines.append(f"Recalled hazard: {format_group(g)}")
        if g.get("crew_note"):
            lines.append(f"  Crew note: {g['crew_note']}")
    for i in w["recalled_incidents"]:
        lines.append(f"Recalled earlier incident: {i['incident_id']} ({i['type']})")
    return "\n".join(lines)
