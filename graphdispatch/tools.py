"""The single place tools are defined: (name, description, JSON schema with graph-derived enums, python function).

Used by graphdispatch/mcp_server.py. Design rule: no tool accepts Cypher or free query text, there is no dispatch
tool and no clear tool, and exactly one tool writes (report_hazard). Enums come from the graph at build time.
"""
import time
from dataclasses import dataclass
from typing import Any, Callable

import jsonschema

from . import db
from .ops import HAZARD_WINDOW_S, RECALL_WINDOW_S, add_hazard, address_id, explain_why, group_hazards, why
from .recommend import recommend


class ToolError(ValueError):
    """Bad tool name or arguments."""


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    fn: Callable[..., Any]
    writes: bool = False


def recommend_units(lat, lon, incident_type):
    r = recommend(lat, lon, incident_type)
    h = r["hospital"]
    return {
        "incident_node": r["incident"]["node"], "snap_m": round(r["incident"]["snap_m"], 1),
        "units": [{"unit_id": u["unit_id"], "capability": u["capability"], "station_id": u["station_id"],
                   "eta_s": round(u["eta_s"], 1)} for u in r["units"]],
        "unmet": r["unmet"], "rule_applied": r["rule_applied"],
        "hospital": None if not h else {
            "needs": h["required_capability"],
            "chosen": h["chosen"] and {"name": h["chosen"]["name"], "eta_s": round(h["chosen"]["eta_s"], 1), "level": h["chosen"].get("level")},
            "nearest": h["nearest"] and {"name": h["nearest"]["name"], "eta_s": round(h["nearest"]["eta_s"], 1)},
            "skipped_reason": h["skipped_reason"]},
        "synthetic": True,
    }


def recall_address(address_label):
    aid, now = address_id(address_label), int(time.time())
    haz = [dict(hazard_id=r[0], kind=r[1], note=r[2], valid_to=r[3], crew_note=r[4])
           for r in db.read("address_hazards", {"address_id": aid, "now": now})]
    inc = [dict(incident_id=r[0], type=r[1], status=r[2], created_at=r[3])
           for r in db.read("address_incidents", {"address_id": aid, "since": now - RECALL_WINDOW_S})]
    return {"address_id": aid, "hazard_groups": group_hazards(haz), "incidents_last_30_days": inc}


def explain_decision(decision_id):
    try:
        w = why(decision_id)
    except KeyError:
        raise ToolError(f"unknown decision_id {decision_id!r}")
    return {"decision": w, "text": explain_why(w)}


def list_open_incidents():
    return [dict(incident_id=r[0], type=r[1], status=r[2], created_at=r[3], address=r[4]) for r in db.read("open_incidents")]


def unit_status():
    return [dict(unit_id=r[0], type=r[1], status=r[2], station_id=r[3], synthetic=True) for r in db.read("unit_status_detail")]


def report_hazard(address_label, kind, note):
    now = int(time.time())
    hid = add_hazard(address_label, kind, note, now, now + HAZARD_WINDOW_S, now=now, reported_by="mcp")
    return {"hazard_id": hid, "address_id": address_id(address_label), "valid_for_days": HAZARD_WINDOW_S // 86400}


def build_tools():
    """Tool definitions with enums read from the graph right now."""
    types = [r[0] for r in db.read("incident_type_names")]
    kinds = [r[0] for r in db.read("hazard_kinds")]
    obj = lambda props, req: {"type": "object", "properties": props, "required": req, "additionalProperties": False}  # noqa: E731
    return [
        Tool("recommend_units", "Rank available units and pick a destination hospital for an incident at a location. "
             "Read-only; does not create an incident or dispatch. Synthetic units.",
             obj({"lat": {"type": "number"}, "lon": {"type": "number"},
                  "incident_type": {"type": "string", "enum": types}}, ["lat", "lon", "incident_type"]), recommend_units),
        Tool("recall_address", "Active hazards (grouped by kind, with crew notes) and incidents in the last 30 days "
             "at an address. Read-only.",
             obj({"address_label": {"type": "string", "minLength": 1, "maxLength": 200}}, ["address_label"]), recall_address),
        Tool("explain_decision", "Explain a recorded decision: units chosen and considered, hospital, skipped hospitals, "
             "route sizes, recalled memory. Read-only.",
             obj({"decision_id": {"type": "string", "minLength": 1, "maxLength": 64}}, ["decision_id"]), explain_decision),
        Tool("list_open_incidents", "List incidents that are open or dispatched. Read-only.", obj({}, []), list_open_incidents),
        Tool("unit_status", "List every unit with type, status and station. Read-only.", obj({}, []), unit_status),
        Tool("report_hazard", "Record a hazard at an address (valid 30 days). The only write tool; it cannot dispatch units.",
             obj({"address_label": {"type": "string", "minLength": 1, "maxLength": 200},
                  "kind": {"type": "string", "enum": kinds},
                  "note": {"type": "string", "minLength": 1, "maxLength": 200}}, ["address_label", "kind", "note"]),
             report_hazard, writes=True),
    ]


def run_tool(name, arguments, tools=None):
    """Validate arguments against the tool's schema (enums included) and call it. Raises ToolError on bad input."""
    tools = tools or build_tools()
    tool = next((t for t in tools if t.name == name), None)
    if tool is None:
        raise ToolError(f"unknown tool {name!r}")
    try:
        jsonschema.validate(arguments or {}, tool.input_schema)
    except jsonschema.ValidationError as e:
        raise ToolError(f"invalid arguments for {name}: {e.message}")
    return tool.fn(**(arguments or {}))
