import random, time, statistics
import pandas as pd
import networkx as nx  # test-only oracle
from pathlib import Path
from common import connect
from qlib import load_queries

PROC = Path(__file__).resolve().parents[3] / "data/processed"
Q = load_queries()
roads = pd.read_csv(PROC / "roads.csv")
G = nx.DiGraph()
for r in roads.itertuples():
    G.add_edge(r.src, r.dst, travel_s=r.travel_s)
comp = max(nx.strongly_connected_components(G), key=len)
print("largest SCC", len(comp), "of", G.number_of_nodes())
nodes = sorted(comp)
rng = random.Random(42)
pairs = []
while len(pairs) < 20:
    s, t = rng.sample(nodes, 2)
    pairs.append((s, t))

g = connect().select_graph("probe_roads")
astar_ok = True
rows = []
for i, (s, t) in enumerate(pairs):
    p = {"src": int(s), "dst": int(t)}
    t0 = time.perf_counter()
    r = g.query(Q["road_sp"], p)
    ms = (time.perf_counter() - t0) * 1000
    fw, fh = r.result_set[0]
    nw, path = nx.single_source_dijkstra(G, s, t, weight="travel_s")
    row = dict(pair_id=i, src=s, dst=t, falkor_weight=fw, nx_weight=nw,
               abs_diff=abs(fw - nw), falkor_hops=fh, nx_hops=len(path) - 1, latency_ms=ms)
    if astar_ok:
        try:
            t0 = time.perf_counter()
            ra = g.query(Q["road_astar"], p)
            row["astar_weight"] = ra.result_set[0][0]
            row["astar_hops"] = ra.result_set[0][1]
            row["astar_latency_ms"] = (time.perf_counter() - t0) * 1000
        except Exception as e:
            astar_ok = False
            print("AStar error:", e)
    rows.append(row)
df = pd.DataFrame(rows)
df.to_csv(Path(__file__).with_name("sp_compare.csv"), index=False)
lat = sorted(df.latency_ms)
print("matches", int((df.abs_diff <= 0.01).sum()), "/20  max_abs_diff", df.abs_diff.max())
print("p50 %.1f p95 %.1f max %.1f" % (statistics.median(lat), lat[int(0.95 * 20) - 1] if False else df.latency_ms.quantile(0.95), lat[-1]))
if "astar_weight" in df:
    print("astar matches", int(((df.astar_weight - df.nx_weight).abs() <= 0.01).sum()),
          "p50 %.1f p95 %.1f" % (df.astar_latency_ms.median(), df.astar_latency_ms.quantile(0.95)))
