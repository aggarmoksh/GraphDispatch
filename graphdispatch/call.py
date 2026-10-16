"""CLI: python -m graphdispatch.call --caller C --address "100 Example Ave" --lat .. --lon .. --type stroke [--dispatch]"""
import argparse

from .ops import dispatch, explain_why, run_call, why
from .recommend import OutOfArea


def main():
    ap = argparse.ArgumentParser(prog="python -m graphdispatch.call")
    ap.add_argument("--caller", required=True, help="synthetic caller id, e.g. caller-001")
    ap.add_argument("--address", required=True)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--type", required=True, dest="incident_type")
    ap.add_argument("--dispatch", action="store_true", help="human confirmation: assign the chosen units")
    a = ap.parse_args()
    try:
        r = run_call(a.caller, a.address, a.lat, a.lon, a.incident_type)
    except OutOfArea as e:
        print("OUT OF AREA:", e)
        return
    print(explain_why(why(r["decision_id"])))
    if a.dispatch:
        print(f"Dispatched {dispatch(r['decision_id'])} units.")
    else:
        print("Not dispatched (re-run with --dispatch to confirm).")


if __name__ == "__main__":
    main()
