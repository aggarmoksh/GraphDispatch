"""FastAPI app: JSON API plus the static single page.

Run: python -m uvicorn graphdispatch.api:app --port 8000
Only /api/call uses the LLM (Bedrock); it is capped server-side (daily and per client). Every other path is graph-only.
Every decision response carries the real Cypher of each query the request ran (the page's Why drawer shows it).
"""
import json
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

os.environ.setdefault("LLM_CALL_CAP", "100000")  # the process cap in llm.py; the real limits are the server-side caps below

from . import db  # noqa: E402
from .intake import IntakeRejected, take_call  # noqa: E402
from .llm import CallCapExceeded  # noqa: E402
from .ops import (DispatchRefused, UnknownHazardKind, add_hazard, address_id, clear, dispatch, explain_why,  # noqa: E402
                  group_hazards, run_call, why)
from .recommend import OutOfArea, fmt_reason  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
DAILY_FILE = ROOT / "runs" / "llm_daily.json"
IP_LIMIT, IP_WINDOW_S = 6, 600
HAZARD_WINDOW_S = 30 * 86400

app = FastAPI(title="GraphDispatch", docs_url="/api/docs", openapi_url="/api/openapi.json")
_lock = threading.Lock()
_ip_calls = defaultdict(deque)


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


# ---------------------------------------------------------------- caps (server-side, cost control)
def _client_ip(request: Request):
    if os.getenv("TRUST_PROXY") == "1":  # only behind a proxy you control
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
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
        ip, now = _client_ip(request), time.time()
        q = _ip_calls[ip]
        while q and now - q[0] > IP_WINDOW_S:
            q.popleft()
        if len(q) >= IP_LIMIT:
            raise HTTPException(429, "Too many AI calls from this connection. Wait a few minutes or switch to Graph only.")
        q.append(now)
        data["count"] += 1
        DAILY_FILE.parent.mkdir(exist_ok=True)
        DAILY_FILE.write_text(json.dumps(data), encoding="utf-8")


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
        "units": [{**u, "reason_text": fmt_reason(u["reason"])} for u in w["chose"]],
        "considered": w["considered"],
        "unmet": [{**m, "reason_text": fmt_reason(m["reason"])} for m in w["unmet"]],
        "destination": w["destination"], "skipped": w["skipped"],
        "recalled_hazard_groups": group_hazards(w["recalled_hazards"]),
        "recalled_incidents": w["recalled_incidents"],
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
    labels = {r[0]: r[1] for r in db.read("count_labels")}
    rels = {r[0]: r[1] for r in db.read("count_rels")}
    hospitals = []
    for osm_id, name, lat, lon, offers in db.read("meta_hospitals"):
        offers = [o for o in offers if o.get("cap")]
        hospitals.append({"osm_id": osm_id, "name": name, "lat": lat, "lon": lon,
                          "capabilities": sorted(o["cap"] for o in offers),
                          "levels": {o["cap"]: o["level"] for o in offers if o.get("level")}})
    return {
        "graph": db.graph_name(), "counts": {"nodes": labels, "relationships": rels},
        "incident_types": [r[0] for r in db.read("incident_type_names")],
        "hazard_kinds": [r[0] for r in db.read("hazard_kinds")],
        "stations": [{"station_id": r[0], "name": r[1], "agency": r[2], "lat": r[3], "lon": r[4]} for r in db.read("meta_stations")],
        "hospitals": hospitals,
        "units": [{"unit_id": r[0], "type": r[1], "status": r[2], "station_id": r[3], "synthetic": True}
                  for r in db.read("unit_status_detail")],
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


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
