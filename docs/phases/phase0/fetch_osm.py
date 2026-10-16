"""Download downtown San Jose drive network and export CSVs."""
import osmnx as ox
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAW, PROC = ROOT / "data/raw", ROOT / "data/processed"
RAW.mkdir(parents=True, exist_ok=True); PROC.mkdir(parents=True, exist_ok=True)

W, S, E, N = -121.910, 37.320, -121.870, 37.350
# osmnx 2.x bbox order is (left, bottom, right, top)
G = ox.graph_from_bbox((W, S, E, N), network_type="drive")
G = ox.add_edge_speeds(G)
G = ox.add_edge_travel_times(G)
ox.save_graphml(G, RAW / "san_jose_drive.graphml")

nodes = pd.DataFrame(
    [(n, d["y"], d["x"]) for n, d in G.nodes(data=True)],
    columns=["osm_id", "lat", "lon"])
nodes.to_csv(PROC / "intersections.csv", index=False)

def nm(v):
    if isinstance(v, list): v = v[0]
    return "" if v is None or (isinstance(v, float) and v != v) else str(v)

rows = [(u, v, d["travel_time"], d["length"], nm(d.get("name")))
        for u, v, d in G.edges(data=True)]
e = pd.DataFrame(rows, columns=["src", "dst", "travel_s", "length_m", "name"])
before = len(e)
e = e.sort_values("travel_s").drop_duplicates(["src", "dst"], keep="first")
e.to_csv(PROC / "roads.csv", index=False)
print(f"nodes={len(nodes)} edges_before={before} edges_after={len(e)} dropped={before-len(e)}")
