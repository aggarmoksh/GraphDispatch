"""Phase 9 probe (graph sjfd_test): does retyping ROAD to CLOSED_ROAD make algo.SPpaths with relTypes ['ROAD'] skip a closed
road, and does ['ROAD','CLOSED_ROAD'] still traverse it? Uses the exact candidate Cypher that becomes queries.cypher.
Run: GRAPH_NAME=sjfd_test python phase9/probe.py
"""
import os
import sys
import time
from pathlib import Path

os.environ["GRAPH_NAME"] = "sjfd_test"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from graphdispatch import db, ops  # noqa: E402
from graphdispatch.recommend import recommend  # noqa: E402
import load  # noqa: E402

CLOSE = ("MATCH (a:Intersection {osm_id: $src}), (b:Intersection {osm_id: $dst}) OPTIONAL MATCH (a)-[f:ROAD]->(b) OPTIONAL MATCH (b)-[r:ROAD]->(a) "
         "WITH a, b, f, r WHERE f IS NOT NULL OR r IS NOT NULL "
         "CREATE (c:Closure {closure_id: $closure_id, reason: $reason, closed_at: $now, expires_at: $expires, src_osm: $src, dst_osm: $dst, name: coalesce(f.name, r.name, ''), synthetic: true}) "
         "CREATE (c)-[:AT]->(a), (c)-[:AT]->(b) "
         "FOREACH (e IN CASE WHEN f IS NULL THEN [] ELSE [f] END | CREATE (a)-[:CLOSED_ROAD {travel_s: e.travel_s, length_m: e.length_m, name: e.name, closure_id: $closure_id}]->(b)) "
         "FOREACH (e IN CASE WHEN r IS NULL THEN [] ELSE [r] END | CREATE (b)-[:CLOSED_ROAD {travel_s: e.travel_s, length_m: e.length_m, name: e.name, closure_id: $closure_id}]->(a)) "
         "FOREACH (e IN CASE WHEN f IS NULL THEN [] ELSE [f] END | DELETE e) "
         "FOREACH (e IN CASE WHEN r IS NULL THEN [] ELSE [r] END | DELETE e) "
         "RETURN c.closure_id AS id")
REOPEN = ("MATCH (c:Closure {closure_id: $closure_id}) WHERE c.reopened_at IS NULL "
          "MATCH (a:Intersection {osm_id: c.src_osm}), (b:Intersection {osm_id: c.dst_osm}) "
          "OPTIONAL MATCH (a)-[f:CLOSED_ROAD {closure_id: $closure_id}]->(b) OPTIONAL MATCH (b)-[r:CLOSED_ROAD {closure_id: $closure_id}]->(a) "
          "FOREACH (e IN CASE WHEN f IS NULL THEN [] ELSE [f] END | CREATE (a)-[:ROAD {travel_s: e.travel_s, length_m: e.length_m, name: e.name}]->(b)) "
          "FOREACH (e IN CASE WHEN r IS NULL THEN [] ELSE [r] END | CREATE (b)-[:ROAD {travel_s: e.travel_s, length_m: e.length_m, name: e.name}]->(a)) "
          "FOREACH (e IN CASE WHEN f IS NULL THEN [] ELSE [f] END | DELETE e) "
          "FOREACH (e IN CASE WHEN r IS NULL THEN [] ELSE [r] END | DELETE e) "
          "SET c.reopened_at = $now RETURN c.closure_id AS id")
SP = ("MATCH (a:Intersection {osm_id: $src}), (b:Intersection {osm_id: $dst}) CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: %s, "
      "relDirection: 'outgoing', weightProp: 'travel_s', pathCount: 1}) YIELD path, pathWeight "
      "RETURN pathWeight, [n IN nodes(path) | n.osm_id] AS nodes, [r IN relationships(path) | type(r)] AS types")


def q(text, params=None):
    return db.graph().query(text, params or {}).result_set


def counts():
    return {"ROAD": q("MATCH ()-[r:ROAD]->() RETURN count(r)")[0][0], "CLOSED_ROAD": q("MATCH ()-[r:CLOSED_ROAD]->() RETURN count(r)")[0][0]}


def main():
    load.load()
    db.write("wipe_runtime")
    out = run_call = ops.run_call("probe", "probe st", 37.33, -121.93, "stroke")
    rec = out["recommendation"]
    hosp = next(r for r in rec["routes"] if r["leg"] == "hospital")["nodes"]
    src, dst = hosp[0], hosp[-1]
    a, b = hosp[len(hosp) // 2], hosp[len(hosp) // 2 + 1]
    print(f"S1 hospital route: {len(hosp)} intersections; the edge to close is the middle one: {a} -> {b}")
    base = q(SP % "['ROAD']", {"src": src, "dst": dst})[0]
    print(f"before closure  relTypes ['ROAD']:               weight {base[0]:.2f} s, uses {a}->{b}: {any(x == a and y == b for x, y in zip(base[1], base[1][1:]))}")
    props_before = q("MATCH (a:Intersection {osm_id: $a})-[r:ROAD]->(b:Intersection {osm_id: $b}) RETURN r.travel_s, r.length_m, r.name", {"a": a, "b": b})
    props_rev = q("MATCH (a:Intersection {osm_id: $b})-[r:ROAD]->(b:Intersection {osm_id: $a}) RETURN r.travel_s, r.length_m, r.name", {"a": a, "b": b})
    c0 = counts()
    print("edge counts before:", c0, "| forward props", props_before, "| reverse edge exists:", bool(props_rev))
    now = int(time.time())
    res = q(CLOSE, {"src": a, "dst": b, "closure_id": "clo-probe", "reason": "probe", "now": now, "expires": now + 1800})
    c1 = counts()
    print("close_road returned:", res, "| edge counts after:", c1)
    closed = q("MATCH (x)-[r:CLOSED_ROAD]->(y) RETURN x.osm_id, y.osm_id, r.travel_s, r.length_m, r.name, r.closure_id")
    print("CLOSED_ROAD edges:", closed)
    open_path = q(SP % "['ROAD']", {"src": src, "dst": dst})[0]
    crosses = lambda nodes: any({x, y} == {a, b} for x, y in zip(nodes, nodes[1:]))
    print(f"after closure   relTypes ['ROAD']:               weight {open_path[0]:.2f} s, uses closed pair: {crosses(open_path[1])}, types {sorted(set(open_path[2]))}")
    free_path = q(SP % "['ROAD', 'CLOSED_ROAD']", {"src": src, "dst": dst})[0]
    print(f"after closure   relTypes ['ROAD','CLOSED_ROAD']: weight {free_path[0]:.2f} s, uses closed pair: {crosses(free_path[1])}, types {sorted(set(free_path[2]))}")
    ok1 = not crosses(open_path[1]) and open_path[0] > base[0] and "CLOSED_ROAD" not in open_path[2]
    ok2 = crosses(free_path[1]) and abs(free_path[0] - base[0]) < 0.01 and "CLOSED_ROAD" in free_path[2]
    back = q(REOPEN, {"closure_id": "clo-probe", "now": now + 5})
    c2 = counts()
    props_after = q("MATCH (a:Intersection {osm_id: $a})-[r:ROAD]->(b:Intersection {osm_id: $b}) RETURN r.travel_s, r.length_m, r.name", {"a": a, "b": b})
    props_rev_after = q("MATCH (a:Intersection {osm_id: $b})-[r:ROAD]->(b:Intersection {osm_id: $a}) RETURN r.travel_s, r.length_m, r.name", {"a": a, "b": b})
    again = q(SP % "['ROAD']", {"src": src, "dst": dst})[0]
    print("reopen_road returned:", back, "| edge counts:", c2, "| restored props equal:", props_after == props_before and props_rev_after == props_rev,
          f"| weight back to {again[0]:.2f} s")
    ok3 = c2 == c0 and props_after == props_before and props_rev_after == props_rev and abs(again[0] - base[0]) < 0.01
    print(f"RESULT: ['ROAD'] skips the closed road: {ok1}; ['ROAD','CLOSED_ROAD'] still traverses it: {ok2}; reopen restores exactly: {ok3}")
    db.write("wipe_runtime")
    q("MATCH (c:Closure) DETACH DELETE c")
    return 0 if ok1 and ok2 and ok3 else 1


if __name__ == "__main__":
    sys.exit(main())
