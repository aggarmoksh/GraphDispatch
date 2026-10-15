import time
import pandas as pd
from pathlib import Path
from common import connect
from qlib import load_queries

PROC = Path(__file__).resolve().parent.parent / "data/processed"
Q = load_queries()
B = 500

def used_memory(db):
    return db.connection.info("memory")["used_memory"]

def main():
    db = connect()
    g = db.select_graph("probe_roads")
    mem_before = used_memory(db)
    try:
        g.query(Q["road_index"])
    except Exception as e:
        if "already indexed" not in str(e).lower():
            raise
    nodes = pd.read_csv(PROC / "intersections.csv").to_dict("records")
    edges = pd.read_csv(PROC / "roads.csv")[["src", "dst", "travel_s", "length_m"]].to_dict("records")
    t0 = time.perf_counter()
    for i in range(0, len(nodes), B):
        g.query(Q["load_nodes"], {"rows": nodes[i:i + B]})
    for i in range(0, len(edges), B):
        g.query(Q["load_edges"], {"rows": edges[i:i + B]})
    secs = time.perf_counter() - t0
    n = g.query(Q["count_nodes"]).result_set[0][0]
    e = g.query(Q["count_edges"]).result_set[0][0]
    print(f"load_seconds={secs:.2f} nodes={n} edges={e}")
    try:
        print("GRAPH.MEMORY USAGE bytes:", db.connection.execute_command("GRAPH.MEMORY", "USAGE", "probe_roads"))
    except Exception as ex:
        print("GRAPH.MEMORY error:", ex)
    mem_after = used_memory(db)
    print(f"used_memory before={mem_before} after={mem_after} delta={mem_after-mem_before}")

if __name__ == "__main__":
    main()
