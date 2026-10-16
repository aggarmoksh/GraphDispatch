"""The frozen configuration-C prompt: template (eval/prompt_template.txt), fact formatting and the forced tool schema.

Standard library only. Frozen by the commit that contains eval/PROTOCOL.md; it must not change afterwards.
"""
from pathlib import Path

import oracle

HERE = Path(__file__).resolve().parent
TOOL_NAME = "dispatch_plan"


def template_parts():
    text = (HERE / "prompt_template.txt").read_text(encoding="utf-8")
    system = text.split("=== SYSTEM ===\n", 1)[1].split("=== USER ===\n", 1)[0].rstrip("\n")
    user = text.split("=== USER ===\n", 1)[1]
    return system, user


def _lines(items, none="none"):
    return "\n".join(items) if items else none


def build(scenario, world=None):
    """Return (system_text, user_text) for one scenario."""
    w = world or oracle.WORLD()
    t = w.types[scenario["incident_type"]]
    status = oracle._status(w, scenario.get("busy_units", []))
    stroke = w.types["stroke"]
    dest = (f"The patient must go to the hospital offering the capability '{t['destination']}' that is fastest to reach."
            if t["destination"] else "No hospital is needed for this incident type.")
    fields = {
        "incident_type": scenario["incident_type"], "lat": scenario["lat"], "lon": scenario["lon"], "address": scenario["address"],
        "requirements": "\n".join(f"- {c}: {n}" for c, n in sorted(t["requires"].items())),
        "destination": dest,
        "hazard_rules": _lines([f"- {r['kind']}: for incident type {r['incident_type']}, add {r['adds_capability']} x{r['count']}"
                                for r in w.hazard_rules if r["adds_capability"]]),
        "stroke_rule": (f"For the incident type stroke the destination capability is '{stroke['destination']}'. Take the fastest hospital "
                        f"offering '{stroke['destination']}' only if (its travel time minus the travel time of the fastest hospital offering "
                        f"'{stroke['fallback']}') is at most {stroke['max_extra_s']} seconds and its own travel time is at most "
                        f"{stroke['max_total_s']} seconds; otherwise take the fastest hospital offering '{stroke['fallback']}'."),
        "active_hazards": _lines([f"- {k}" for k in sorted(set(scenario.get("hazards", [])))]),
        "prior_incidents": _lines([f"- {k}, within the last 30 days" for k in sorted(scenario.get("prior_incidents", []))]),
        "stations": "\n".join(f"- station {sid}: latitude {lat:.5f}, longitude {lon:.5f}" for sid, (lat, lon) in sorted(w.stations.items())),
        "units": "\n".join(f"- {u}: station {d['station_id']}, status {status[u]}, capabilities {', '.join(sorted(d['capabilities']))}"
                           for u, d in sorted(w.units.items())),
        "hospitals": "\n".join(f"- {h['name']}: latitude {h['lat']:.5f}, longitude {h['lon']:.5f}, offers {', '.join(sorted(h['capabilities']))}"
                               for h in sorted(w.hospitals, key=lambda h: h["osm_id"])),
    }
    system, user = template_parts()
    return system, user.format(**fields)


def tool(world=None):
    """The forced tool: unit ids, capabilities and hospital names are enums built from the seed tables."""
    w = world or oracle.WORLD()
    caps = sorted({c for d in w.units.values() for c in d["capabilities"]})
    return {
        "name": TOOL_NAME,
        "description": "Submit the dispatch plan: units chosen per capability and the destination hospital.",
        "input_schema": {
            "type": "object",
            "properties": {
                "assignments": {"type": "array", "items": {"type": "object", "properties": {
                    "capability": {"type": "string", "enum": caps},
                    "unit_ids": {"type": "array", "items": {"type": "string", "enum": sorted(w.units)}}},
                    "required": ["capability", "unit_ids"]}},
                "hospital": {"type": "string", "enum": [h["name"] for h in sorted(w.hospitals, key=lambda h: h["osm_id"])] + ["none"]},
                "recalled_facts": {"type": "array", "items": {"type": "string", "maxLength": 120}},
            },
            "required": ["assignments", "hospital", "recalled_facts"],
        },
    }
