"""Post-hoc "seconds lost" analysis (NOT pre-registered). Reads eval/results_raw.json and road times from the oracle's world.

For each scenario and configuration:
  unit delay     = sum over required capabilities of (road ETA of the config's units for that capability
                   minus road ETA of the oracle's units for that capability)
  hospital delay = road ETA incident -> config's hospital minus the oracle's hospital ETA
A capability or hospital the configuration did not cover cannot be given a time; it is counted as "uncovered" and left out of
the sums. Values are signed: the oracle's greedy rule is not globally optimal, so a configuration can be faster on one item.
No Bedrock calls. Appends (or replaces) a labeled section in eval/RESULTS.md; every earlier number is left unchanged.
"""
import csv
import json
import statistics
import sys
from pathlib import Path

import networkx as nx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import oracle  # noqa: E402

MARK = "## Added after the results; not pre-registered: seconds lost"


def main():
    raw = json.loads((HERE / "results_raw.json").read_text(encoding="utf-8"))
    scen = {s["id"]: s for s in json.loads((HERE / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]}
    w = oracle.WORLD()
    rev = w.graph.reverse(copy=False)
    station_node = {sid: w.snap(*ll)[0] for sid, ll in w.stations.items()}
    rows, out = [], {}
    for sid, sc in scen.items():
        node, _ = w.snap(sc["lat"], sc["lon"])
        dist = nx.single_source_dijkstra_path_length(rev, node, weight="travel_s")
        road = {u: dist.get(station_node[d["station_id"]]) for u, d in w.units.items()}
        ora = raw["oracle"][sid]
        for cfg in raw["configs_run"]:
            res = next(r for r in raw["rows"] if r["scenario"] == sid and r["config"] == cfg)["result"]
            unit_delay, hosp_delay, uncovered = 0.0, 0.0, 0
            for cap, req in ora["requirements"].items():
                mine = [u["unit_id"] for u in res["units"] if u["capability"] == cap]
                theirs = [u["eta_s"] for u in ora["units"] if u["capability"] == cap]
                if len(mine) < req["need"] or any(road.get(u) is None for u in mine):
                    uncovered += 1
                    continue
                unit_delay += sum(road[u] for u in mine[:req["need"]]) - sum(theirs)
            if ora["hospital"]:
                if res["hospital"] is None or res["hospital"] not in ora["hospital_etas"]:
                    uncovered += 1
                else:
                    hosp_delay = ora["hospital_etas"][res["hospital"]] - ora["hospital"]["eta_s"]
            rows.append({"scenario": sid, "config": cfg, "unit_delay_s": round(unit_delay, 1), "hospital_delay_s": round(hosp_delay, 1),
                         "total_s": round(unit_delay + hosp_delay, 1), "uncovered_items": uncovered})
    with (HERE / "seconds_lost.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)

    names = {"A": "A GraphDispatch", "B": "B Straight-line", "C": "C LLM with facts as text"}
    md = [MARK, "", "Computed from `eval/results_raw.json` and the oracle's road times by `eval/seconds_lost.py` after the results were known; "
          "it adds no Bedrock calls and changes none of the numbers above. Per scenario: unit delay is the sum over required capabilities of "
          "(road ETA of the chosen unit minus road ETA of the oracle's unit); hospital delay is the same for the destination hospital. "
          "Values are signed (the oracle's greedy rule is not globally optimal, so a configuration can be faster on one item). "
          "Anything a configuration did not cover (for example a missing hazmat unit) has no time and is counted as uncovered, not added.", "",
          "| configuration | total seconds lost (24 scenarios) | median per scenario | max in one scenario | scenarios with seconds lost | uncovered items |",
          "|---|---|---|---|---|---|"]
    for cfg in raw["configs_run"]:
        r = [x for x in rows if x["config"] == cfg]
        tot = [x["total_s"] for x in r]
        md.append(f"| {names[cfg]} | {sum(tot):.0f} | {statistics.median(tot):.1f} | {max(tot):.0f} | {sum(1 for t in tot if t > 0.01)} | {sum(x['uncovered_items'] for x in r)} |")
    worst = {}
    for cfg in ("B", "C"):
        r = sorted((x for x in rows if x["config"] == cfg), key=lambda x: -x["total_s"])[:3]
        worst[cfg] = ", ".join(f"{x['scenario']} (+{x['total_s']:.0f} s)" for x in r)
    md += ["", f"Largest single-scenario losses: B {worst['B']}; C {worst['C']}. Per-scenario values: `eval/seconds_lost.csv`.", ""]

    path = HERE / "RESULTS.md"
    text = path.read_text(encoding="utf-8")
    if MARK in text:
        text = text.split(MARK)[0].rstrip("\n") + "\n"
    path.write_text(text.rstrip("\n") + "\n\n" + "\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
