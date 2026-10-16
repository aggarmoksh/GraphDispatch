"""Safe reset of runtime data. Dry run by default.

  python scripts/reset.py --graph sjfd            # dry run: counts of runtime labels only, no changes
  python scripts/reset.py --graph sjfd --yes      # delete runtime labels, reset unit statuses to seed values

Only graphs sjfd and sjfd_test are allowed. Runtime labels: Incident, Decision, Caller, Address, Hazard.
Seed labels (roads, stations, hospitals, units, capabilities, incident types, hazard kinds) are never deleted.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

ALLOWED = ("sjfd", "sjfd_test")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", default="sjfd")
    ap.add_argument("--yes", action="store_true", help="actually delete runtime data (default is a dry run)")
    a = ap.parse_args()
    if a.graph not in ALLOWED:
        sys.exit(f"refusing graph {a.graph!r}; allowed: {', '.join(ALLOWED)}")
    os.environ["GRAPH_NAME"] = a.graph
    from graphdispatch import db
    import load

    def table(name):
        return {r[0]: r[1] for r in db.read(name)}

    print(f"graph={a.graph} mode={'RESET' if a.yes else 'dry run (no changes)'}")
    print("runtime labels:       ", table("runtime_label_counts"))
    print("runtime relationships:", table("runtime_rel_counts"))
    seed_before = (table("seed_label_counts"), table("seed_rel_counts"))
    if not a.yes:
        print("seed labels (unchanged):", seed_before[0])
        return
    db.write("wipe_runtime")
    load.reset_units()
    seed_after = (table("seed_label_counts"), table("seed_rel_counts"))
    print("seed labels before:", seed_before[0])
    print("seed labels after: ", seed_after[0])
    print("seed relationships before:", seed_before[1])
    print("seed relationships after: ", seed_after[1])
    if seed_before != seed_after:
        sys.exit("ERROR: seed counts changed")
    print("seed counts identical; runtime after:", table("runtime_label_counts"))


if __name__ == "__main__":
    main()
