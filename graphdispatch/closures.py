"""Road closures: retype ROAD to CLOSED_ROAD so algo.SPpaths with relTypes ['ROAD'] skips them (no new algorithm).

A closure is a (:Closure) node attached to both intersections; reopening restores the edges exactly and keeps the node
(marked reopened) so earlier decisions that routed around it stay explainable. Limits for the public site live in the API.
"""
import os
import time
import uuid

from . import db


class ClosureError(Exception):
    """The road could not be closed or reopened (unknown, already closed, or already reopened)."""


def _now(now):
    return int(time.time()) if now is None else int(now)


def expire_minutes():
    return float(os.getenv("DEMO_EXPIRE_MIN", "30"))


def close_road(src, dst, reason="Synthetic closure", now=None, expire_min=None):
    """Close the road between two intersections (both directions where they exist). Returns the closure id."""
    now = _now(now)
    expire_min = expire_minutes() if expire_min is None else expire_min
    closure_id = f"clo-{uuid.uuid4().hex[:10]}"
    rows = db.write("close_road", {"src": int(src), "dst": int(dst), "closure_id": closure_id, "reason": reason[:80],
                                   "now": now, "expires": int(now + expire_min * 60)})
    if not rows:
        raise ClosureError("There is no open road between those intersections (unknown, or already closed).")
    return closure_id


def nearest_segment(lat, lon):
    rows = db.read("nearest_road_segment", {"lat": float(lat), "lon": float(lon)})
    if not rows:
        raise ClosureError("No open road found near that point.")
    src, dst, name, dist = rows[0]
    return {"src": src, "dst": dst, "name": name, "dist_m": float(dist)}


def close_near(lat, lon, reason="Synthetic closure", now=None):
    seg = nearest_segment(lat, lon)
    return close_road(seg["src"], seg["dst"], reason, now=now), seg


def reopen_road(closure_id, now=None):
    rows = db.write("reopen_road", {"closure_id": closure_id, "now": _now(now)})
    if not rows:
        raise ClosureError("That closure does not exist or is already reopened.")
    return closure_id


def list_closures():
    out = []
    for cid, reason, name, closed_at, expires_at, src, dst, a_lat, a_lon, b_lat, b_lon in db.read("closures_list"):
        out.append({"closure_id": cid, "reason": reason, "name": name, "closed_at": closed_at, "expires_at": expires_at,
                    "src_osm": src, "dst_osm": dst,
                    "geometry": [[a_lon, a_lat], [b_lon, b_lat]], "synthetic": True})
    return out


def active_count():
    return db.read("active_closure_count")[0][0]


def reopen_all():
    """Reopen every active closure (used by reset helpers so no road stays closed)."""
    n = 0
    for c in list_closures():
        reopen_road(c["closure_id"])
        n += 1
    return n


def expire_closures(now=None):
    """Reopen closures whose expiry time has passed. Returns how many were reopened."""
    now = _now(now)
    n = 0
    for (cid,) in db.read("expired_closures", {"now": now}):
        try:
            reopen_road(cid, now=now)
            n += 1
        except ClosureError:
            pass
    return n
