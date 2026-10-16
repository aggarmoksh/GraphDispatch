"""Run the Phase 7 evaluation as pre-registered in eval/PROTOCOL.md.

  GRAPH_NAME=sjfd_test python eval/run.py            # runs A, then B, then C (24 Bedrock calls at most 26)
  python eval/run.py --report-only [--price-in X --price-out Y]   # rebuild RESULTS.md from results_raw.json

A is checked against the oracle first; if it differs on any scenario the run stops there (B and C are not run).
Scoring and reporting follow the protocol exactly; nothing here changes the prompt, scenarios or oracle.
"""
import argparse
import csv
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
os.environ["GRAPH_NAME"] = "sjfd_test"
os.environ["LLM_CALL_CAP"] = "26"          # protocol section 9: 24 scenarios plus at most 2 transport retries
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(HERE))

import networkx as nx  # noqa: E402

import baselines  # noqa: E402
import oracle  # noqa: E402
import prompt  # noqa: E402

SCENARIOS = json.loads((HERE / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
CONFIGS = ("A", "B", "C")
STROKES = {"S1", "R03", "R10", "R17"}
ETA_TOL = 0.01


def p95(xs):
    xs = sorted(xs)
    return xs[math.ceil(0.95 * len(xs)) - 1]


# ---------------------------------------------------------------- scoring (protocol section 7)
def score(sc, ora, res, world):
    """res: {units: [{unit_id, capability}], hospital: name|None, recalled_hazards: [...], recalled_incident_types: [...] , recalled_text: str}"""
    status = oracle._status(world, sc.get("busy_units", []))
    ids = [u["unit_id"] for u in res["units"]]
    out = {"unit_set_match": set(ids) == {u["unit_id"] for u in ora["units"]}}
    ok = len(ids) == len(set(ids))
    for cap, req in ora["requirements"].items():
        have = {u["unit_id"] for u in res["units"] if u["capability"] == cap and status.get(u["unit_id"]) == "available"
                and cap in world.units.get(u["unit_id"], {"capabilities": set()})["capabilities"]}
        ok &= len(have) >= req["need"]
    out["required_covered"] = bool(ok)
    out["hazard_unit_included"] = ("HM26" in ids) if sc["id"] == "O1" else None
    want_h = ora["hospital"]["name"] if ora["hospital"] else None
    out["hospital_correct"] = (res["hospital"] == want_h) if want_h else None
    out["stroke_rule_correct"] = (res["hospital"] == want_h) if sc["id"] in STROKES else None
    if sc["id"] == "O2":
        out["memory_recall"] = ("oxygen_storage" in res["recalled_hazards"]) and ("structure_fire" in res["recalled_incident_types"])
    else:
        out["memory_recall"] = None
    return out


def a_matches(sc, ora, res):
    """Protocol section 8: the strict check of A against the oracle."""
    problems = []
    mine = {u["unit_id"]: u for u in res["units"]}
    theirs = {u["unit_id"]: u for u in ora["units"]}
    if set(mine) != set(theirs):
        problems.append(f"unit set {sorted(mine)} != oracle {sorted(theirs)}")
    for u in set(mine) & set(theirs):
        if mine[u]["capability"] != theirs[u]["capability"]:
            problems.append(f"{u} covers {mine[u]['capability']} but oracle {theirs[u]['capability']}")
        if abs(mine[u]["eta_s"] - theirs[u]["eta_s"]) > ETA_TOL:
            problems.append(f"{u} eta {mine[u]['eta_s']:.3f} vs oracle {theirs[u]['eta_s']:.3f}")
    if ora["hospital"] or res["hospital"]:
        want = ora["hospital"]["name"] if ora["hospital"] else None
        if res["hospital"] != want:
            problems.append(f"hospital {res['hospital']} != oracle {want}")
        elif want and abs(res["hospital_eta"] - ora["hospital"]["eta_s"]) > ETA_TOL:
            problems.append(f"hospital eta {res['hospital_eta']:.3f} vs oracle {ora['hospital']['eta_s']:.3f}")
    if bool(res["unmet"]) != bool(ora["unmet"]):
        problems.append(f"unmet {res['unmet']} vs oracle {ora['unmet']}")
    if sc["id"] == "O2":
        if sorted(set(res["recalled_hazards"])) != ora["recall"]["hazards"] or sorted(set(res["recalled_incident_types"])) != ora["recall"]["prior_incident_types"]:
            problems.append(f"recall {res['recalled_hazards']}/{res['recalled_incident_types']} vs oracle {ora['recall']}")
    return problems


# ---------------------------------------------------------------- configuration A
def run_a(world):
    from graphdispatch import db, ops
    import load
    load.load()                                    # idempotent: make sure the seed is in sjfd_test
    db.write("wipe_runtime")                       # reset runtime data
    for u in world.units:
        db.write("set_unit_status", {"unit_id": u, "status": "available"})
    results = {}
    for sc in SCENARIOS:
        for u in sc["busy_units"]:
            db.write("set_unit_status", {"unit_id": u, "status": "busy"})
        now = int(time.time())
        if sc["id"] == "O1":
            ops.add_hazard(sc["address"], "oxygen_storage", "eval: oxygen cylinders", now - 10, now + 30 * 86400, now=now, reported_by="eval")
        t0 = time.perf_counter()
        out = ops.run_call(f"caller-eval-{sc['id']}", sc["address"], sc["lat"], sc["lon"], sc["incident_type"])
        ms = (time.perf_counter() - t0) * 1000
        rec = out["recommendation"]
        h = rec["hospital"]["chosen"] if rec["hospital"] and rec["hospital"]["chosen"] else None
        results[sc["id"]] = {
            "units": [{"unit_id": u["unit_id"], "capability": u["capability"], "eta_s": u["eta_s"]} for u in rec["units"]],
            "hospital": h["name"] if h else None, "hospital_eta": h["eta_s"] if h else None, "unmet": rec["unmet"],
            "recalled_hazards": [x["kind"] for x in out["recalled"]["hazards"]],
            "recalled_incident_types": [x["type"] for x in out["recalled"]["incidents"]],
            "latency_ms": ms, "error": None}
        for u in sc["busy_units"]:
            db.write("set_unit_status", {"unit_id": u, "status": "available"})
    return results


# ---------------------------------------------------------------- configuration B
def run_b(world):
    results = {}
    for sc in SCENARIOS:
        t0 = time.perf_counter()
        r = baselines.solve(sc, world)
        ms = (time.perf_counter() - t0) * 1000
        results[sc["id"]] = {"units": r["units"], "hospital": r["hospital"]["name"] if r["hospital"] else None,
                             "hospital_eta": r["hospital"]["eta_s"] if r["hospital"] else None,
                             "recalled_hazards": [], "recalled_incident_types": [], "latency_ms": ms, "error": None}
    return results


# ---------------------------------------------------------------- configuration C
def is_transport_error(e):
    import botocore.exceptions as bx
    return isinstance(e, (bx.ClientError, bx.ConnectionError, bx.ReadTimeoutError, bx.ConnectTimeoutError, bx.EndpointConnectionError))


def run_c(world):
    from graphdispatch import llm
    tool = prompt.tool(world)
    results = {}
    for sc in SCENARIOS:
        system, user = prompt.build(sc, world)
        res, err = None, None
        for attempt in (1, 2):                                          # one transport retry at most
            try:
                res = llm.converse(system, [{"role": "user", "content": user}], tools=[tool], max_tokens=600, force_tool=prompt.TOOL_NAME)
                err = None
                break
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:160]}"
                if attempt == 1 and is_transport_error(e) and not isinstance(e, llm.CallCapExceeded):
                    continue
                break
        row = {"units": [], "hospital": None, "hospital_eta": None, "recalled_hazards": [], "recalled_incident_types": [],
               "latency_ms": None, "input_tokens": None, "output_tokens": None, "error": err, "raw": None}
        if res is not None:
            row.update(latency_ms=res["latency_ms"], input_tokens=res["input_tokens"], output_tokens=res["output_tokens"], raw=res["tool_input"])
            ti = res["tool_input"]
            if res["tool_name"] != prompt.TOOL_NAME or not isinstance(ti, dict):
                row["error"] = "reply did not call dispatch_plan"
            else:
                try:
                    row["units"] = [{"unit_id": u, "capability": a["capability"]} for a in ti["assignments"] for u in a["unit_ids"]]
                    row["hospital"] = None if ti["hospital"] == "none" else ti["hospital"]
                    text = " ".join(ti.get("recalled_facts", [])).lower()
                    row["recalled_hazards"] = ["oxygen_storage"] if "oxygen" in text else []
                    row["recalled_incident_types"] = ["structure_fire"] if "structure" in text else []
                except (KeyError, TypeError) as e:
                    row["error"] = f"schema: {type(e).__name__}"
                    row["units"], row["hospital"] = [], None
        results[sc["id"]] = row
    return results


# ---------------------------------------------------------------- report
def road_etas(sc, world):
    node, _ = world.snap(sc["lat"], sc["lon"])
    dist = nx.single_source_dijkstra_path_length(world.graph.reverse(copy=False), node, weight="travel_s")
    station_node = {sid: world.snap(*ll)[0] for sid, ll in world.stations.items()}
    return {u: dist.get(station_node[d["station_id"]]) for u, d in world.units.items()}


def describe(res, world, sc, road, label):
    units = ", ".join(f"{u['unit_id']} for {u['capability']}" + (f" ({u['eta_s']:.0f} s {label})" if "eta_s" in u else "") for u in res["units"]) or "none"
    return f"units {units}; hospital {res['hospital'] or 'none'}"


def explain(sc, cfg, res, ora, world):
    road = road_etas(sc, world)
    mine, theirs = {u["unit_id"] for u in res["units"]}, {u["unit_id"] for u in ora["units"]}
    lines = []
    for u in sorted(mine - theirs):
        lines.append(f"{cfg} chose {u} (road time {road[u]:.0f} s), which the oracle did not")
    for u in sorted(theirs - mine):
        e = next(x for x in ora["units"] if x["unit_id"] == u)
        lines.append(f"the oracle chose {u} for {e['capability']} (road time {e['eta_s']:.0f} s), which {cfg} did not")
    want = ora["hospital"]["name"] if ora["hospital"] else None
    if res["hospital"] != want:
        he = ora["hospital_etas"]
        lines.append(f"hospital: {cfg} chose {res['hospital']} (road time {he.get(res['hospital'], float('nan')):.0f} s), the oracle {want} "
                     f"({ora['hospital']['eta_s']:.0f} s; rule {ora['hospital_rule']})" if want else f"hospital: {cfg} chose {res['hospital']} where none is needed")
    for cap, req in ora["requirements"].items():
        if any(s.startswith("hazard:") for s in req["sources"]) and not any(u["capability"] == cap for u in res["units"]):
            lines.append(f"the {cap} unit added by the active hazard is missing from {cfg}'s answer")
    return lines or [f"{cfg} differs only in assignment details"]


def build_report(raw, price_in, price_out, calls_made):
    world = oracle.WORLD()
    scen = {s["id"]: s for s in SCENARIOS}
    stats = {}
    for cfg in raw["configs_run"]:
        rows = [r for r in raw["rows"] if r["config"] == cfg]
        agg = {}
        for m in ("unit_set_match", "required_covered", "hazard_unit_included", "hospital_correct", "stroke_rule_correct", "memory_recall"):
            vals = [r["metrics"][m] for r in rows if r["metrics"][m] is not None]
            agg[m] = (sum(1 for v in vals if v), len(vals))
        lat = [r["latency_ms"] for r in rows if r["latency_ms"] is not None]
        agg["latency"] = (statistics.median(lat), p95(lat)) if lat else (None, None)
        stats[cfg] = agg
    names = {"A": "A GraphDispatch", "B": "B Straight-line", "C": "C LLM with facts as text"}
    md = ["# Phase 7 results", "", "Protocol: eval/PROTOCOL.md (commit " + raw["protocol_commit"] + "). Scoring against eval/oracle.py. Results are reported as produced.", ""]
    if "C" not in raw["configs_run"]:
        md.append(f"**The run stopped after A: {raw['stop_reason']}**\n")
    md += ["## Summary (correct / applicable)", "", "| metric | " + " | ".join(names[c] for c in raw["configs_run"]) + " |", "|---|" + "---|" * len(raw["configs_run"])]
    labels = [("unit_set_match", "Exact unit-set match (24)"), ("required_covered", "Every required capability covered (24)"),
              ("hazard_unit_included", "Hazard-added unit included (O1)"), ("hospital_correct", "Correct hospital"),
              ("stroke_rule_correct", "Stroke rule applied correctly (4 strokes)"), ("memory_recall", "Memory recall (O2)")]
    for key, label in labels:
        md.append(f"| {label} | " + " | ".join(f"{stats[c][key][0]} / {stats[c][key][1]}" for c in raw["configs_run"]) + " |")
    md.append("| Latency median / p95 (ms) | " + " | ".join(f"{stats[c]['latency'][0]:.1f} / {stats[c]['latency'][1]:.1f}" for c in raw["configs_run"]) + " |")
    if "C" in raw["configs_run"]:
        crow = [r for r in raw["rows"] if r["config"] == "C"]
        tin, tout = sum(r["result"].get("input_tokens") or 0 for r in crow), sum(r["result"].get("output_tokens") or 0 for r in crow)
        md += ["", "## Configuration C usage", "",
               f"- Bedrock calls in this phase: {calls_made} (limit 26). Input tokens {tin:,}, output tokens {tout:,} ({tin // max(1, len(crow)):,} in and {tout // max(1, len(crow))} out per scenario).",
               (f"- Estimated cost at the AWS Bedrock list price of ${price_in}/M input and ${price_out}/M output tokens: ${tin / 1e6 * price_in + tout / 1e6 * price_out:.4f} for the 24 scenarios."
                if price_in is not None else "- Price not verified (the AWS Bedrock pricing page could not be reached): tokens only."),
               "- C errors: " + (", ".join(f"{r['scenario']}: {r['result']['error']}" for r in crow if r["result"].get("error")) or "none")]
    md += ["", "## Per scenario (unit set / hospital correct)", "", "| scenario | type | " + " | ".join(raw["configs_run"]) + " |", "|---|---|" + "---|" * len(raw["configs_run"])]
    for s in SCENARIOS:
        cells = []
        for c in raw["configs_run"]:
            r = next(x for x in raw["rows"] if x["config"] == c and x["scenario"] == s["id"])
            m = r["metrics"]
            cells.append(("units ok" if m["unit_set_match"] else "units differ") + ("" if m["hospital_correct"] is None else (", hospital ok" if m["hospital_correct"] else ", hospital differs")))
        md.append(f"| {s['id']} | {s['incident_type']} | " + " | ".join(cells) + " |")

    # worked examples, chosen by the protocol's rule (section 9)
    def differs(cfg, sid, units_only=False):
        r = next(x for x in raw["rows"] if x["config"] == cfg and x["scenario"] == sid)
        m = r["metrics"]
        return (not m["unit_set_match"]) if units_only else (not m["unit_set_match"] or m["hospital_correct"] is False)
    picks = []
    b_first = next((s["id"] for s in SCENARIOS if "B" in raw["configs_run"] and differs("B", s["id"], True)), None)
    c_first = next((s["id"] for s in SCENARIOS if "C" in raw["configs_run"] and differs("C", s["id"])), None)
    both = next((s["id"] for s in SCENARIOS if "B" in raw["configs_run"] and "C" in raw["configs_run"] and differs("B", s["id"]) and differs("C", s["id"])
                 and s["id"] not in (b_first, c_first)), None)
    for tag, sid in (("first scenario where B's unit set differs", b_first), ("first scenario where C's unit set or hospital differs", c_first),
                     ("first scenario where both differ (not already shown)", both)):
        if sid:
            picks.append((tag, sid))
    md += ["", "## Worked examples (selected by the protocol's rule)", ""]
    if not picks:
        md.append("No scenario had B or C disagree with the oracle.")
    for tag, sid in picks:
        sc = scen[sid]
        ora = raw["oracle"][sid]
        md += [f"### {sid}: {sc['name']} ({tag})", "",
               f"Incident {sc['incident_type']} at {sc['lat']}, {sc['lon']}" + (f"; busy units {sc['busy_units']}" if sc["busy_units"] else "")
               + (f"; active hazards {sc['hazards']}" if sc["hazards"] else ""), "",
               f"- Oracle: units " + ", ".join(f"{u['unit_id']} for {u['capability']} ({u['eta_s']:.0f} s by road)" for u in ora["units"])
               + f"; hospital " + (f"{ora['hospital']['name']} ({ora['hospital']['eta_s']:.0f} s)" if ora["hospital"] else "none")]
        for cfg in raw["configs_run"]:
            r = next(x for x in raw["rows"] if x["config"] == cfg and x["scenario"] == sid)
            md.append(f"- {names[cfg]}: " + describe(r["result"], world, sc, None, "straight-line" if cfg == "B" else "by road"))
        for cfg in ("B", "C"):
            if cfg in raw["configs_run"] and differs(cfg, sid):
                r = next(x for x in raw["rows"] if x["config"] == cfg and x["scenario"] == sid)
                md.append(f"- Why the oracle differs from {cfg}: " + "; ".join(explain(sc, cfg, r["result"], ora, world)) + ".")
        md.append("")
    md += ["## Reading these numbers", "",
           "- 24 synthetic scenarios and one temperature-0 run are a demonstration, not a statistical study (protocol section 10).",
           "- A and the oracle share rules written by the same author; the oracle differs in code and method, and its numbers were confirmed independently, but this does not test whether the rules are medically right.",
           "- C had every fact as text but no road network, by design. B had the same tables with straight-line distances and no memory."]
    (HERE / "RESULTS.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--skip-c", action="store_true", help="run A and B only, print a summary, write no result files, make no Bedrock call")
    ap.add_argument("--price-in", type=float)
    ap.add_argument("--price-out", type=float)
    args = ap.parse_args()
    raw_path = HERE / "results_raw.json"
    if args.report_only:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        build_report(raw, args.price_in, args.price_out, raw["calls_made"])
        print("RESULTS.md rebuilt")
        return 0

    import subprocess
    commit = subprocess.run(["git", "log", "-1", "--format=%h", "--", "eval/PROTOCOL.md"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    log = ROOT / "runs" / "llm_calls.log"
    log_before = len(log.read_text().splitlines()) if log.exists() else 0
    world = oracle.WORLD()
    ora = {s["id"]: oracle.solve(s, world) for s in SCENARIOS}
    raw = {"protocol_commit": commit, "configs_run": [], "rows": [], "oracle": ora, "stop_reason": None}

    def add(cfg, results):
        raw["configs_run"].append(cfg)
        for s in SCENARIOS:
            r = results[s["id"]]
            if r.get("error"):   # an errored answer is wrong wherever the metric applies
                empty = {"units": [], "hospital": None, "recalled_hazards": [], "recalled_incident_types": []}
                m = {k: (None if v is None else False) for k, v in score(s, ora[s["id"]], empty, world).items()}
            else:
                m = score(s, ora[s["id"]], r, world)
            raw["rows"].append({"scenario": s["id"], "config": cfg, "metrics": m, "latency_ms": r["latency_ms"], "result": r})

    # ---- A first, checked strictly against the oracle
    a = run_a(world)
    add("A", a)
    bad = {s["id"]: a_matches(s, ora[s["id"]], a[s["id"]]) for s in SCENARIOS}
    bad = {k: v for k, v in bad.items() if v}
    if bad and args.skip_c:
        print("STOP (skip-c): A does not match the oracle:", json.dumps(bad, indent=1))
        return 1
    if bad:
        raw["stop_reason"] = "A disagrees with the oracle on " + ", ".join(bad) + ": " + json.dumps(bad)
        raw["calls_made"] = 0
        _write(raw, 0)
        build_report(raw, None, None, 0)
        print("STOP: A does not match the oracle:", json.dumps(bad, indent=1))
        return 1
    print("A matches the oracle on 24 of 24")
    add("B", run_b(world))
    print("B done")
    if args.skip_c:
        for cfg in ("A", "B"):
            rows = [r for r in raw["rows"] if r["config"] == cfg]
            print(cfg, {m: sum(1 for r in rows if r["metrics"][m]) for m in ("unit_set_match", "required_covered", "hospital_correct", "stroke_rule_correct", "memory_recall", "hazard_unit_included")})
        return 0
    add("C", run_c(world))
    calls = len(log.read_text().splitlines()) - log_before if log.exists() else 0
    raw["calls_made"] = calls
    _write(raw, calls)
    build_report(raw, args.price_in, args.price_out, calls)
    print(f"C done; Bedrock calls this run: {calls}")
    return 0


def _write(raw, calls):
    (HERE / "results_raw.json").write_text(json.dumps(raw, indent=1, default=str), encoding="utf-8")
    cols = ["scenario", "config", "unit_set_match", "required_covered", "hazard_unit_included", "hospital_correct", "stroke_rule_correct",
            "memory_recall", "latency_ms", "input_tokens", "output_tokens", "units", "hospital", "oracle_units", "oracle_hospital", "error"]
    with (HERE / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in raw["rows"]:
            res, ora = r["result"], raw["oracle"][r["scenario"]]
            w.writerow({"scenario": r["scenario"], "config": r["config"], **r["metrics"],
                        "latency_ms": None if r["latency_ms"] is None else round(r["latency_ms"], 2),
                        "input_tokens": res.get("input_tokens"), "output_tokens": res.get("output_tokens"),
                        "units": ";".join(f"{u['unit_id']}:{u['capability']}" for u in res["units"]), "hospital": res["hospital"],
                        "oracle_units": ";".join(f"{u['unit_id']}:{u['capability']}" for u in ora["units"]),
                        "oracle_hospital": ora["hospital"]["name"] if ora["hospital"] else None, "error": res.get("error")})


if __name__ == "__main__":
    sys.exit(main())
