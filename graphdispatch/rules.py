"""Pure decision logic (no database access)."""


def stroke_bypass(capable, fallback, max_extra_s, max_total_s, source="AHA Mission: Lifeline Stroke EMS algorithm"):
    """Pick between the best EVT-capable hospital and the best stroke-primary fallback hospital.

    capable / fallback: dict with "name" and "eta_s", or None.
    Uses the capable hospital only if (capable_eta - fallback_eta) <= max_extra_s and capable_eta <= max_total_s.
    Returns (chosen, rule_applied, used_capable).
    """
    if capable is None and fallback is None:
        return None, "no hospital offers the needed or fallback capability", False
    if capable is None:
        return fallback, f"no capable hospital; routed to {fallback['name']} ({fallback['eta_s']:.0f} s)", False
    if fallback is None:
        return capable, f"{capable['name']} is the only option ({capable['eta_s']:.0f} s)", True
    extra = capable["eta_s"] - fallback["eta_s"]
    total = capable["eta_s"]
    if extra <= max_extra_s and total <= max_total_s:
        return capable, (f"{capable['name']} {extra:+.0f} s over {fallback['name']}, within {max_extra_s:.0f} s "
                         f"AHA bypass limit (total {total:.0f} s <= {max_total_s:.0f} s; {source})"), True
    why = (f"{extra:+.0f} s over {fallback['name']} exceeds {max_extra_s:.0f} s AHA bypass limit" if extra > max_extra_s
           else f"total {total:.0f} s exceeds {max_total_s:.0f} s limit")
    return fallback, f"{capable['name']} {why}; routed to {fallback['name']} ({fallback['eta_s']:.0f} s; {source})", False
