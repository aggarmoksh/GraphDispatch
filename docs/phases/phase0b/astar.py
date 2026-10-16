import sys, time
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "phase0"))
from common import connect
from qlib import load_queries

HERE = Path(__file__).resolve().parent
db = connect()
g = db.select_graph("probe_roads")
res = g.query("CALL dbms.procedures()")
print("header:", res.header)
for row in res.result_set:
    if "AStar" in str(row[0]):
        for h, c in zip(res.header, row):
            print(" ", h[1], "=", c)
Q = load_queries()
cmp_ = pd.read_csv(HERE.parent / "phase0" / "sp_compare.csv")
rows = []
for r in cmp_.itertuples():
    t0 = time.perf_counter()
    res = g.query(Q["road_astar"], {"src": int(r.src), "dst": int(r.dst)})
    ms = (time.perf_counter() - t0) * 1000
    w, h = res.result_set[0]
    rows.append(dict(pair_id=r.pair_id, sp_weight=r.falkor_weight, astar_weight=w,
                     abs_diff=abs(w - r.falkor_weight), astar_hops=h, astar_latency_ms=ms,
                     sp_latency_ms=r.latency_ms))
df = pd.DataFrame(rows)
df.drop(columns="sp_latency_ms").to_csv(HERE / "astar_compare.csv", index=False)
print("matches", int((df.abs_diff <= 0.01).sum()), "/20 max", df.abs_diff.max())
print("astar p50 %.2f p95 %.2f | sp p50 %.2f p95 %.2f" % (
    df.astar_latency_ms.median(), df.astar_latency_ms.quantile(.95),
    df.sp_latency_ms.median(), df.sp_latency_ms.quantile(.95)))
