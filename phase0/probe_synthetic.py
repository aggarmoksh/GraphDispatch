from common import connect
from qlib import load_queries

Q = load_queries()
db = connect()
db.select_graph("probe_synth").delete() if "probe_synth" in db.list_graphs() else None
g = db.select_graph("probe_synth")
for n in "ABCDE":
    g.query(Q["synth_node"], {"name": n})
# direct A->E is 1 hop but expensive; A-B-C-D-E is 4 hops and cheapest (40)
edges = [("A","B",10),("B","C",10),("C","D",10),("D","E",10),("A","E",100),("A","C",30),("C","E",30)]
for s, d, w in edges:
    g.query(Q["synth_edge"], {"src": s, "dst": d, "w": w})
r = g.query(Q["synth_sp"], {"src": "A", "dst": "E"})
print(r.result_set)
names, weight, hops = r.result_set[0]
assert names == ["A","B","C","D","E"], names
assert abs(weight - 40) < 1e-9, weight
print("SYNTHETIC PASS", names, weight)
