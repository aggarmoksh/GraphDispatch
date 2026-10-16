"""FastAPI app: JSON API plus the static single page.

Run: python -m uvicorn graphdispatch.api:app --port 8000
Only /api/call uses the LLM (Bedrock); it is capped server-side (daily and per client). Every other path is graph-only.
Every decision response carries the real Cypher of each query the request ran (the page's Why drawer shows it).
"""
import asyncio
import csv
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

os.environ.setdefault("LLM_CALL_CAP", "100000")  # the process cap in llm.py; the real limits are the server-side caps below

from . import closures, db  # noqa: E402
from .closures import ClosureError  # noqa: E402
from .intake import IntakeRejected, take_call  # noqa: E402
from .llm import CallCapExceeded  # noqa: E402
from .ops import (DispatchRefused, UnknownHazardKind, add_hazard, address_id, clear, dispatch, expire_stale,  # noqa: E402
                  explain_why, group_hazards, run_call, why)
from .recommend import OutOfArea, fmt_reason  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
DAILY_FILE = ROOT / "runs" / "llm_daily.json"
IP_LIMIT, IP_WINDOW_S = 6, 600
CLOSE_IP_LIMIT = 10                 # close actions per client per IP_WINDOW_S (public-site limit)
DEMO_CLOSURES_CSV = ROOT / "seed" / "demo_closures.csv"
HAZARD_WINDOW_S = 30 * 86400

log = logging.getLogger("graphdispatch")


async def _expiry_loop():
    """Every DEMO_EXPIRY_INTERVAL_S (default 300) free units held by stale demo incidents. Runs once at startup too."""
    while True:
        try:
            expired, freed = await asyncio.to_thread(expire_stale)
            if expired:
                log.info("expired %s stale incidents, freed %s units", expired, freed)
            reopened = await asyncio.to_thread(closures.expire_closures)
            if reopened:
                log.info("reopened %s expired closures", reopened)
        except Exception as e:  # the demo must keep serving even if one sweep fails
            log.warning("expiry sweep failed: %s", e)
        await asyncio.sleep(float(os.getenv("DEMO_EXPIRY_INTERVAL_S", "300")))


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(_expiry_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="GraphDispatch", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
_lock = threading.Lock()
_ip_calls = defaultdict(deque)
_close_calls = defaultdict(deque)
_close_lock = threading.Lock()


# ---------------------------------------------------------------- request models
class CallIn(BaseModel):
    text: str = Field(min_length=3, max_length=500)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class RecommendIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    incident_type: str = Field(min_length=1, max_length=40)
    address: str = Field(default="", max_length=200)


class HazardIn(BaseModel):
    address: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=40)
    note: str = Field(min_length=1, max_length=200)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


class ClosureIn(BaseModel):
    """Close the road nearest to a point (lat, lon) or the road between two intersections (src_osm, dst_osm)."""
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    src_osm: int | None = None
    dst_osm: int | None = None
    reason: str = Field(default="Synthetic closure", min_length=1, max_length=80)

    @model_validator(mode="after")
    def _one_form(self):
        by_point = self.lat is not None and self.lon is not None
        by_pair = self.src_osm is not None and self.dst_osm is not None
        if by_point == by_pair:
            raise ValueError("Give either lat and lon, or src_osm and dst_osm.")
        return self


# ---------------------------------------------------------------- caps (server-side, cost control)
def _strip_port(addr):
    """'1.2.3.4:5678' -> '1.2.3.4'; '[2001:db8::1]:5678' -> '2001:db8::1'; a bare IPv6 address is returned unchanged."""
    addr = addr.strip()
    if addr.startswith("["):
        return addr[1:addr.index("]")] if "]" in addr else addr
    if addr.count(":") == 1:
        return addr.split(":")[0]
    return addr


def client_ip(request: Request):
    """The address the per-IP limit counts.

    TRUST_PROXY=0 (default): the socket peer; forwarding headers are ignored, so a visitor cannot choose their key.
    TRUST_PROXY=1 (only behind CloudFront or a load balancer that sets these headers): CloudFront-Viewer-Address if
    present (port stripped), else the RIGHTMOST X-Forwarded-For entry, the one our own proxy appended. The leftmost
    entries are client-supplied and are never used.
    """
    if os.getenv("TRUST_PROXY") == "1":
        viewer = request.headers.get("cloudfront-viewer-address")
        if viewer:
            return _strip_port(viewer)
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            parts = [x.strip() for x in fwd.split(",") if x.strip()]
            if parts:
                return parts[-1]
    return request.client.host if request.client else "unknown"


def check_and_count_llm_call(request: Request):
    """Raise 429 if the daily or per-IP cap is hit; otherwise count this call. Counted before the call is made."""
    cap = int(os.getenv("LLM_DAILY_CAP", "150"))
    today = datetime.now(timezone.utc).date().isoformat()
    msg = "Daily AI limit reached. Switch to Graph only to keep testing."
    with _lock:
        try:
            data = json.loads(DAILY_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if data.get("date") != today:
            data = {"date": today, "count": 0}
        if data["count"] >= cap:
            raise HTTPException(429, msg)
        ip, now = client_ip(request), time.time()
        q = _ip_calls[ip]
        while q and now - q[0] > IP_WINDOW_S:
            q.popleft()
        if len(q) >= IP_LIMIT:
            raise HTTPException(429, "Too many AI calls from this connection. Wait a few minutes or switch to Graph only.")
        q.append(now)
        data["count"] += 1
        DAILY_FILE.parent.mkdir(exist_ok=True)
        DAILY_FILE.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------- labels and rule parsing
_LABELS = None


def labels():
    """Plain-language labels from seed/capability_labels.csv and seed/incident_type_labels.csv."""
    global _LABELS
    if _LABELS is None:
        def load(name):
            with (ROOT / "seed" / name).open(newline="", encoding="utf-8") as f:
                return {r["id"]: r["label"] for r in csv.DictReader(f)}
        _LABELS = {"capabilities": load("capability_labels.csv"), "incident_types": load("incident_type_labels.csv")}
    return _LABELS


_RULE_PATTERNS = [
    ("bypass_used", re.compile(r"^(?P<capable>.+?) (?P<extra>[+-]\d+) s over (?P<fallback>.+?), within (?P<max_extra>\d+) s AHA bypass limit "
                               r"\(total (?P<total>\d+) s <= (?P<max_total>\d+) s; (?P<source>.+)\)$")),
    ("bypass_declined_extra", re.compile(r"^(?P<capable>.+?) (?P<extra>[+-]\d+) s over (?P<fallback>.+?) exceeds (?P<max_extra>\d+) s AHA bypass limit; "
                                         r"routed to (?P=fallback) \((?P<eta>\d+) s; (?P<source>.+)\)$")),
    ("bypass_declined_total", re.compile(r"^(?P<capable>.+?) total (?P<total>\d+) s exceeds (?P<max_total>\d+) s limit; "
                                         r"routed to (?P<fallback>.+?) \((?P<eta>\d+) s; (?P<source>.+)\)$")),
    ("fastest", re.compile(r"^fastest hospital offering (?P<capability>\w+): (?P<hospital>.+) \((?P<eta>\d+) s\)$")),
    ("no_destination", re.compile(r"^no destination hospital required for (?P<incident_type>\w+)$")),
    ("none_offer", re.compile(r"^no hospital offers (?P<capability>\w+)$")),
]


def parse_rule(text):
    """Turn the sentence rules.py / recommend.py write into numbers the page can render in plain language."""
    for kind, pat in _RULE_PATTERNS:
        m = pat.match(text)
        if m:
            out = {"kind": kind}
            for k, v in m.groupdict().items():
                out[k] = int(v) if k in ("extra", "max_extra", "total", "max_total", "eta") else v
            return out
    return {"kind": "other", "text": text}


def max_closures():
    return int(os.getenv("MAX_ACTIVE_CLOSURES", "3"))


def demo_closures():
    """Rows of seed/demo_closures.csv (the preset closes these, then reruns S1)."""
    with DEMO_CLOSURES_CSV.open(newline="", encoding="utf-8") as f:
        return [{**r, "src_osm": int(r["src_osm"]), "dst_osm": int(r["dst_osm"]), "lat": float(r["lat"]), "lon": float(r["lon"])}
                for r in csv.DictReader(f)]


def check_close_limit(request: Request):
    """At most CLOSE_IP_LIMIT close actions per client per window (the same client-IP rules as the AI cap)."""
    ip, now = client_ip(request), time.time()
    with _lock:
        q = _close_calls[ip]
        while q and now - q[0] > IP_WINDOW_S:
            q.popleft()
        if len(q) >= CLOSE_IP_LIMIT:
            raise HTTPException(429, f"Too many road closures from this connection ({CLOSE_IP_LIMIT} per {IP_WINDOW_S // 60} minutes). Wait a few minutes.")
        q.append(now)


# ---------------------------------------------------------------- payload
def _with_cypher(recorded):
    qs = db.queries()
    return [{"name": r["name"], "cypher": qs[r["name"]], "ms": round(r["ms"], 2), "params": r["params"]} for r in recorded]


def _incident(incident_id):
    rows = db.read("incident_info", {"incident_id": incident_id})
    if not rows:
        return None
    iid, itype, status, lat, lon, created_at, aid, label = rows[0]
    return {"incident_id": iid, "type": itype, "status": status, "lat": lat, "lon": lon, "created_at": created_at,
            "address": label}


def decision_payload(decision_id, classification=None):
    w = why(decision_id)
    inc = _incident(w["incident"]["incident_id"])
    legs = {}
    for r in w["route"]:
        legs.setdefault(r["leg"], []).append(r)
    routes = [{"leg": leg, "kind": "hospital" if leg == "hospital" else "unit",
               "coords": [[p["lon"], p["lat"]] for p in sorted(rows, key=lambda p: p["seq"])]}
              for leg, rows in sorted(legs.items())]
    return {
        "decision_id": decision_id, "agent": w["agent"], "incident": inc, "rule_applied": w["rule_applied"],
        "rule": parse_rule(w["rule_applied"]),
        "units": [{**u, "reason_text": fmt_reason(u["reason"])} for u in w["chose"]],
        "considered": w["considered"],
        "unmet": [{**m, "reason_text": fmt_reason(m["reason"])} for m in w["unmet"]],
        "destination": w["destination"], "skipped": w["skipped"],
        "recalled_hazard_groups": group_hazards(w["recalled_hazards"]),
        "recalled_incidents": w["recalled_incidents"],
        "rerouted": w["rerouted"], "changes": w["changes"], "no_route": w["no_route"],
        "routes": routes, "classification": classification, "text": explain_why(w),
        "synthetic": True,
    }


def respond(build, status_code=200):
    """Run build() while recording queries; attach the real Cypher and timings to the JSON result."""
    t0 = time.perf_counter()
    with db.record_queries() as rec:
        body = build()
    body["queries"] = _with_cypher(rec)
    body["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return JSONResponse(body, status_code=status_code)


def _new_caller():
    return f"caller-{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------- endpoints
@app.get("/api/health")
def health():
    try:
        n = db.read("health_ping")[0][0]
    except Exception:
        return JSONResponse({"ok": False, "error": "FalkorDB is not reachable. Start it and retry."}, status_code=503)
    return {"ok": True, "graph": db.graph_name(), "intersections": n}


@app.get("/api/meta")
def meta():
    node_counts = {r[0]: r[1] for r in db.read("count_labels")}
    rels = {r[0]: r[1] for r in db.read("count_rels")}
    hospitals = []
    for osm_id, name, lat, lon, offers in db.read("meta_hospitals"):
        offers = [o for o in offers if o.get("cap")]
        hospitals.append({"osm_id": osm_id, "name": name, "lat": lat, "lon": lon,
                          "capabilities": sorted(o["cap"] for o in offers),
                          "levels": {o["cap"]: o["level"] for o in offers if o.get("level")}})
    return {
        "graph": db.graph_name(), "counts": {"nodes": node_counts, "relationships": rels},
        "incident_types": [r[0] for r in db.read("incident_type_names")],
        "hazard_kinds": [r[0] for r in db.read("hazard_kinds")],
        "stations": [{"station_id": r[0], "name": r[1], "agency": r[2], "lat": r[3], "lon": r[4]} for r in db.read("meta_stations")],
        "hospitals": hospitals,
        "units": [{"unit_id": r[0], "type": r[1], "status": r[2], "station_id": r[3], "synthetic": True}
                  for r in db.read("unit_status_detail")],
        "labels": labels(),
        "demo_closures": demo_closures(),
        "closure_limits": {"max_active": max_closures(), "expire_min": closures.expire_minutes(), "per_ip": f"{CLOSE_IP_LIMIT} per {IP_WINDOW_S // 60} minutes"},
        "llm": {"daily_cap": int(os.getenv("LLM_DAILY_CAP", "150")), "per_ip": f"{IP_LIMIT} per {IP_WINDOW_S // 60} minutes"},
    }


@app.post("/api/call")
def api_call(body: CallIn, request: Request):
    check_and_count_llm_call(request)
    try:
        def build():
            r = take_call(_new_caller(), body.text, body.lat, body.lon)
            c = r["classification"]
            return decision_payload(r["decision_id"], classification={
                "incident_type": c["incident_type"], "hazards": c["hazards"], "address": c["address_label_used"],
                "model_note": c["reason"], "llm_ms": round(r["llm_ms"])})
        return respond(build)
    except IntakeRejected:
        raise HTTPException(422, "The AI reply was not a valid classification, so nothing was saved. Rephrase the call or switch to Graph only.")
    except OutOfArea as e:
        raise HTTPException(422, f"That location is outside the mapped area: {e}. Click inside the map's road network.")
    except CallCapExceeded:
        raise HTTPException(429, "Daily AI limit reached. Switch to Graph only to keep testing.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502, "The AI service did not answer. Try again, or switch to Graph only.")


@app.post("/api/recommend")
def api_recommend(body: RecommendIn):
    types = [r[0] for r in db.read("incident_type_names")]
    if body.incident_type not in types:
        raise HTTPException(422, f"Unknown incident type {body.incident_type!r}. Choose one of: {', '.join(types)}.")
    label = body.address.strip() or f"device@{body.lat:.4f},{body.lon:.4f}"
    try:
        return respond(lambda: decision_payload(
            run_call(_new_caller(), label, body.lat, body.lon, body.incident_type)["decision_id"]))
    except OutOfArea as e:
        raise HTTPException(422, f"That location is outside the mapped area: {e}. Click inside the map's road network.")


@app.get("/api/decision/{decision_id}")
def api_decision(decision_id: str):
    try:
        return respond(lambda: decision_payload(decision_id))
    except KeyError:
        raise HTTPException(404, f"No decision {decision_id}. It may belong to another graph or was reset.")


@app.post("/api/dispatch/{decision_id}")
def api_dispatch(decision_id: str):
    def build():
        why(decision_id)  # raises KeyError for an unknown decision (404, not a refusal)
        dispatch(decision_id)
        return decision_payload(decision_id)
    try:
        return respond(build)
    except DispatchRefused as e:
        raise HTTPException(409, f"{e}. Nothing was changed; take the call again for fresh units.")
    except KeyError:
        raise HTTPException(404, f"No decision {decision_id}.")


@app.post("/api/clear/{incident_id}")
def api_clear(incident_id: str):
    def build():
        if _incident(incident_id) is None:
            raise KeyError(incident_id)
        n = clear(incident_id)
        return {"incident_id": incident_id, "units_released": n, "status": "cleared"}
    try:
        return respond(build)
    except KeyError:
        raise HTTPException(404, f"No incident {incident_id}.")


@app.get("/api/incidents")
def incidents():
    now = int(time.time())

    def build():
        return {
            "incidents": [{"incident_id": r[0], "type": r[1], "status": r[2], "created_at": r[3], "address": r[4]}
                          for r in db.read("open_incidents")],
            "hazards": [{"hazard_id": r[0], "kind": r[1], "note": r[2], "address": r[3], "lat": r[4], "lon": r[5], "crew_note": r[6]}
                        for r in db.read("active_hazards_map", {"now": now})],
            "units": [{"unit_id": r[0], "status": r[2], "station_id": r[3]} for r in db.read("unit_status_detail")],
        }
    return respond(build)


@app.post("/api/hazard")
def api_hazard(body: HazardIn):
    now = int(time.time())

    def build():
        hid = add_hazard(body.address, body.kind, body.note, now, now + HAZARD_WINDOW_S, now=now, reported_by="operator",
                         lat=body.lat, lon=body.lon)
        return {"hazard_id": hid, "address_id": address_id(body.address), "valid_for_days": HAZARD_WINDOW_S // 86400}
    try:
        return respond(build)
    except UnknownHazardKind as e:
        raise HTTPException(422, str(e))


# ---------------------------------------------------------------- road closures (public-site limits: cap, expiry, per-IP)
def _closure_queries():
    q = db.queries()
    return {"close_road": q["close_road"], "reopen_road": q["reopen_road"]}


def _closure_view(cid):
    return next((c for c in closures.list_closures() if c["closure_id"] == cid), None)


@app.get("/api/closures")
def api_closures_list():
    def build():
        return {"closures": closures.list_closures(), "limit": max_closures(), "expire_min": closures.expire_minutes(),
                "now": int(time.time()), "closure_queries": _closure_queries()}
    return respond(build)


@app.post("/api/closures")
def api_close_road(body: ClosureIn, request: Request):
    check_close_limit(request)

    def build():
        with _close_lock:
            if closures.active_count() >= max_closures():
                raise HTTPException(409, f"{max_closures()} roads are already closed on this demo (the limit). Reopen one before closing another.")
            try:
                if body.src_osm is not None:
                    seg = {"src": body.src_osm, "dst": body.dst_osm, "name": None, "dist_m": 0.0}
                else:
                    seg = closures.nearest_segment(body.lat, body.lon)
                cid = closures.close_road(seg["src"], seg["dst"], body.reason)
            except ClosureError as e:
                raise HTTPException(409, str(e))
        return {"closure": _closure_view(cid), "snapped_m": round(seg["dist_m"], 1), "closure_queries": _closure_queries()}
    return respond(build)


@app.delete("/api/closures/{closure_id}")
def api_reopen_road(closure_id: str):
    def build():
        try:
            closures.reopen_road(closure_id)
        except ClosureError:
            raise HTTPException(404, f"No active closure {closure_id}. It may already be reopened or have expired.")
        return {"closure_id": closure_id, "status": "reopened"}
    return respond(build)


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
