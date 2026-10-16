"""CLI: python -m graphdispatch.take_call --caller ID --lat X --lon Y --text "..." [--address "..."]

One Bedrock call per invocation. Prints the classification (without the uncalibrated confidence) and the
decision explanation. Never dispatches.
"""
import argparse

from .intake import IntakeRejected, take_call
from .recommend import OutOfArea


def main():
    ap = argparse.ArgumentParser(prog="python -m graphdispatch.take_call", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--caller", required=True, help="synthetic caller id, e.g. caller-201")
    ap.add_argument("--lat", type=float, required=True, help="device latitude")
    ap.add_argument("--lon", type=float, required=True, help="device longitude")
    ap.add_argument("--text", required=True, help="the caller's words (synthetic)")
    ap.add_argument("--address", default=None, help="address override")
    a = ap.parse_args()
    try:
        r = take_call(a.caller, a.text, a.lat, a.lon, address_override=a.address)
    except IntakeRejected as e:
        print("INTAKE REJECTED:", e)
        return
    except OutOfArea as e:
        print("OUT OF AREA:", e)
        return
    c = r["classification"]
    print(f"Classified as {c['incident_type']}; hazards reported by caller: {', '.join(c['hazards']) or 'none'}; "
          f"address used: {c['address_label_used']}")
    if c["reason"]:
        print(f"Model note: {c['reason']}")
    print(r["explanation"])
    print(f"take_call {r['latency_ms']:.0f} ms (LLM {r['llm_ms']:.0f} ms). Not dispatched.")


if __name__ == "__main__":
    main()
