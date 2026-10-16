"""Generate QUERIES.md (and docs/seed_counts.json) from graphdispatch/queries.cypher.

For every named query: purpose, Cypher text, which Python functions call it, read or write, and the median milliseconds over
20 runs on graph sjfd_test with representative parameters. Timing is skipped for index and load queries (they run once at
load time) and for state-changing queries that cannot be repeated meaningfully (wipe, set status, dispatch, clear, expire).
Also records GRAPH.EXPLAIN for unit_candidates and effective_requirements and GRAPH.PROFILE for effective_requirements.

Usage: python scripts/gen_queries_md.py        (needs FalkorDB; uses and cleans the test graph sjfd_test only)
"""
import ast
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["GRAPH_NAME"] = "sjfd_test"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from graphdispatch import closures, db, ops  # noqa: E402
import load  # noqa: E402

RUNS = 20
WRITE_RE = re.compile(r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE)\b")
SKIP_TIMING = {
    "wipe_runtime": "state-changing (deletes every runtime node)",
    "set_unit_status": "state-changing (sets one unit's status)",
    "dispatch": "state-dependent (succeeds once, then refuses)",
    "clear": "state-dependent (frees units once)",
    "expire_incidents": "state-dependent (expires only stale incidents)",
    "close_road": "state-changing (closes a road; closing the same road twice is refused)",
    "reopen_road": "state-changing (reopens a closure once)",
}


def purposes():
    text = (ROOT / "graphdispatch" / "queries.cypher").read_text(encoding="utf-8")
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"-- \[(\w+)\] ([^\n]*)", text)}


def callers(names):
    """Map query name -> sorted list of 'file: function (db.read|db.write)' from the Python sources (ast)."""
    found = {n: set() for n in names}
    files = sorted((ROOT / "graphdispatch").glob("*.py")) + sorted((ROOT / "scripts").glob("*.py"))
    for f in files:
        if f.name == "gen_queries_md.py":
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        rel = f.relative_to(ROOT).as_posix()

        def visit(node, func):
            for child in ast.iter_child_nodes(node):
                fn = func
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn = child.name
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr in ("read", "write") \
                        and isinstance(child.func.value, ast.Name) and child.func.value.id == "db" and child.args \
                        and isinstance(child.args[0], ast.Constant) and child.args[0].value in found:
                    found[child.args[0].value].add(f"{rel}: {fn or '(module)'} (db.{child.func.attr})")
                elif isinstance(child, ast.Constant) and isinstance(child.value, str) and child.value in found and \
                        not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("read", "write")):
                    found[child.value].add(f"{rel}: {fn or '(module)'} (name listed in the file)")
                visit(child, fn)
        visit(tree, None)
    # INDEXES is a module-level list that load() iterates; say so instead of "(module)"
    for n in names:
        found[n] = {c.replace("(module)", "load, through the INDEXES list") for c in found[n]}
    return {n: sorted(v) for n, v in found.items()}


def setup():
    """Seed counts, then runtime data to time against."""
    db.drop_graph()
    load.load()
    counts = {"nodes": {r[0]: r[1] for r in db.read("seed_label_counts")}, "relationships": {r[0]: r[1] for r in db.read("seed_rel_counts")}}
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "seed_counts.json").write_text(json.dumps({
        "source": "scripts/gen_queries_md.py: a fresh load of seed/ into sjfd_test by scripts/load.py, runtime labels excluded",
        "nodes": counts["nodes"], "relationships": counts["relationships"],
        "nodes_total": sum(counts["nodes"].values()), "relationships_total": sum(counts["relationships"].values())}, indent=1), encoding="utf-8")
    now = int(time.time())
    ops.add_hazard("10 Query Timing St", "oxygen_storage", "timing hazard", now - 10, now + 86400, now=now)
    stroke = ops.run_call("caller-timing", "10 Query Timing St", 37.33, -121.93, "stroke", now=now)
    fire = ops.run_call("caller-timing2", "10 Query Timing St", 37.336, -121.89, "structure_fire", now=now)
    cands = db.read("unit_candidates", {"caps": ["als"]})
    c0_src, c0_dst = db.read("nearest_road_segment", {"lat": 37.30, "lon": -121.84})[0][:2]
    c_id = closures.close_road(c0_src, c0_dst, "timing closure", now=now)      # one closure to time the provenance queries against
    return {"closure_id": c_id, "now": now, "stroke": stroke, "fire": fire, "src": cands[0][3], "dst": stroke["recommendation"]["incident"]["node"],
            "route_nodes": [n for n in db.read("route", {"src": cands[0][3], "dst": stroke["recommendation"]["incident"]["node"]})[0][1]][:20]}


def params_for(name, i, c):
    inc, dec = c["fire"]["incident_id"], c["stroke"]["decision_id"]
    now = c["now"]
    table = {
        "snap_station": {"id": 7, "lat": 37.34126, "lon": -121.91672}, "snap_hospital": {"id": 403207487, "lat": 37.36212, "lon": -121.84936},
        "snap_incident": {"lat": 37.33, "lon": -121.93}, "unit_candidates": {"caps": ["als", "transport"]},
        "required_caps": {"name": "stroke"}, "dest_capability": {"name": "stroke"}, "eta": {"src": c["src"], "dst": c["dst"]},
        "route": {"src": c["src"], "dst": c["dst"]},
        "create_incident": {"caller_id": "caller-t", "address_id": f"timing {i}", "label": f"timing {i}", "lat": 37.33, "lon": -121.93, "type": "stroke",
                            "node": c["dst"], "incident_id": f"inc-time-{i}", "now": now, "call_text": None, "intake_model": None, "created_ns": time.time_ns()},
        "incident_info": {"incident_id": inc}, "recall_incidents": {"incident_id": inc, "since": now - 30 * 86400},
        "recall_hazards": {"incident_id": inc, "now": now},
        "add_hazard": {"address_id": "10 query timing st", "label": "10 Query Timing St", "hazard_id": f"haz-time-{i}", "kind": "oxygen_storage",
                       "note": "t", "valid_from": now - 10, "valid_to": now + 86400, "now": now, "created_ns": time.time_ns(), "reported_by": None,
                       "lat": None, "lon": None},
        "hazard_reported_in": {"hazard_id": f"haz-time-{max(i - 1, 0)}", "incident_id": inc},
        "decision_create": {"decision_id": f"dec-time-{i}", "incident_id": inc, "ts": now, "rule_applied": "timing", "unmet": [], "unmet_reasons": [],
                            "changes": "{}", "no_route": []},
        "nearest_road_segment": {"lat": 37.33, "lon": -121.93}, "eta_all": {"src": c["src"], "dst": c["dst"]}, "route_all": {"src": c["src"], "dst": c["dst"]},
        "expired_closures": {"now": now},
        "decision_rerouted": {"decision_id": dec, "rows": [{"leg": "hospital", "closure_id": c["closure_id"], "extra_s": 12.5}]},
        "decision_considered": {"decision_id": dec, "rows": [{"unit_id": "E7", "capability": "als", "eta_s": 1.0, "rank": 1}]},
        "decision_chose": {"decision_id": dec, "rows": [{"unit_id": "E7", "capability": "als", "eta_s": 1.0, "reason": "base"}]},
        "decision_destination": {"decision_id": dec, "osm_id": 403207487, "eta_s": 551.0, "level": None},
        "decision_skipped": {"decision_id": dec, "rows": [{"osm_id": 38899283, "eta_s": 49.0, "reason": "timing"}]},
        "decision_route": {"decision_id": dec, "rows": [{"leg": "E7", "seq": k, "node": n} for k, n in enumerate(c["route_nodes"])]},
        "decision_recalled_hazards": {"decision_id": dec, "ids": ["haz-time-0"]},
        "decision_recalled_incidents": {"decision_id": dec, "ids": [inc]},
        "why": {"decision_id": dec}, "decision_units": {"decision_id": dec},
        "effective_requirements": {"incident_id": inc, "now": now},
        "address_hazards": {"address_id": "10 query timing st", "now": now},
        "address_incidents": {"address_id": "10 query timing st", "since": now - 30 * 86400}, "active_hazards_map": {"now": now},
    }
    return table.get(name, {})


def time_queries(q, c):
    out = {}
    for name, text in q.items():
        if name.startswith(("idx_", "load_")) or name in ("snap_station", "snap_hospital"):
            out[name] = "not timed: index and load queries run once at load time"
            continue
        if name in SKIP_TIMING:
            out[name] = "not timed: " + SKIP_TIMING[name]
            continue
        fn = db.write if WRITE_RE.search(text) else db.read
        fn(name, params_for(name, 0, c))                      # one warm-up run, not counted
        ms = []
        for i in range(1, RUNS + 1):
            t = []
            fn(name, params_for(name, i, c), t)
            ms.append(t[0][1])
        out[name] = round(statistics.median(ms), 2)
    return out


def plans(c):
    g = db.graph()
    q = db.queries()
    inc = c["fire"]["incident_id"]
    res = {}
    res["EXPLAIN unit_candidates"] = str(g.explain(q["unit_candidates"], {"caps": ["als", "transport"]}))
    res["EXPLAIN effective_requirements"] = str(g.explain(q["effective_requirements"], {"incident_id": inc, "now": c["now"]}))
    res["PROFILE effective_requirements"] = str(g.profile(q["effective_requirements"], {"incident_id": inc, "now": c["now"]}))
    return res


def main():
    q, why = db.queries(), purposes()
    assert set(q) == set(why), "every query needs a one-line comment"
    call = callers(list(q))
    c = setup()
    timing = time_queries(q, c)
    pl = plans(c)

    md = ["# Cypher queries", "",
          "Generated by `scripts/gen_queries_md.py` from [graphdispatch/queries.cypher](graphdispatch/queries.cypher). Do not edit by hand: "
          "`tests/test_queries_md.py` fails if the names or the Cypher text here differ from the source.", "",
          f"All {len(q)} named queries are listed. Every runtime query is parameterized (`$name`), never built with string formatting. "
          "Reads go through `db.read` (GRAPH.RO_QUERY), writes through `db.write` (GRAPH.QUERY); `graphdispatch/db.py` is the only module that talks to FalkorDB.", "",
          f"**Timing:** the median of {RUNS} runs (after one warm-up run) on graph `sjfd_test` with representative parameters, measured at generation time on a laptop. "
          "Not timed: the index and load queries (they run once when the seed is loaded) and queries that change state in a way that cannot be repeated meaningfully "
          "(`wipe_runtime`, `set_unit_status`, `dispatch`, `clear`, `expire_incidents`).", "",
          "## Summary", "", "| query | kind | median ms | purpose |", "|---|---|---|---|"]
    for n, t in q.items():
        kind = "write" if WRITE_RE.search(t) else "read"
        ms = timing[n] if not isinstance(timing[n], str) else "not timed"
        md.append(f"| `{n}` | {kind} | {ms} | {why[n]} |")
    md += ["", "## Queries", ""]
    for n, t in q.items():
        kind = "write" if WRITE_RE.search(t) else "read"
        md += [f"### `{n}`", "", f"- Purpose: {why[n]}", f"- Kind: {kind}",
               "- Called from: " + ("; ".join(call[n]) if call[n] else "no production caller (used by tests, the API or scripts through another path)"),
               "- Median: " + (f"{timing[n]} ms over {RUNS} runs" if not isinstance(timing[n], str) else timing[n]), "",
               "```cypher", t, "```", ""]
    md += ["## Execution plans", "",
           "Output of `GRAPH.EXPLAIN` and `GRAPH.PROFILE` on `sjfd_test` (fire incident at an address with an active hazard), as returned by FalkorDB.", ""]
    for title, text in pl.items():
        md += [f"### {title}", "", "```text", text.rstrip(), "```", ""]
    (ROOT / "QUERIES.md").write_text("\n".join(md), encoding="utf-8")

    closures.reopen_all()
    db.write("wipe_runtime")
    load.reset_units()
    slow = sorted(((v, k) for k, v in timing.items() if not isinstance(v, str)), reverse=True)[:3]
    print(f"{len(q)} queries; slowest three by median ms: " + ", ".join(f"{k} {v}" for v, k in slow))
    print("timed:", sum(1 for v in timing.values() if not isinstance(v, str)), "not timed:", sum(1 for v in timing.values() if isinstance(v, str)))


if __name__ == "__main__":
    main()
