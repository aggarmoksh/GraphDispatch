"""Download the B2 drive network, keep the largest strongly connected component, export CSVs."""
from pathlib import Path
import osmnx as ox
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW, PROC = ROOT / "data/raw", ROOT / "data/processed"
RAW.mkdir(parents=True, exist_ok=True); PROC.mkdir(parents=True, exist_ok=True)

W, S, E, N = -121.945, 37.300, -121.840, 37.370  # B2
G = ox.graph_from_bbox((W, S, E, N), network_type="drive")
G = ox.add_edge_speeds(G)
G = ox.add_edge_travel_times(G)
n0, e0 = G.number_of_nodes(), G.number_of_edges()
G = ox.truncate.largest_component(G, strongly=True)
n1, e1 = G.number_of_nodes(), G.number_of_edges()
ox.save_graphml(G, RAW / "b2_drive.graphml")

pd.DataFrame([(n, d["y"], d["x"]) for n, d in G.nodes(data=True)],
             columns=["osm_id", "lat", "lon"]).to_csv(PROC / "b2_intersections.csv", index=False)

def nm(v):
    if isinstance(v, list):
        v = v[0]
    return "" if v is None or (isinstance(v, float) and v != v) else str(v)

e = pd.DataFrame([(u, v, d["travel_time"], d["length"], nm(d.get("name")))
                  for u, v, d in G.edges(data=True)],
                 columns=["src", "dst", "travel_s", "length_m", "name"])
m0 = len(e)
e = e.sort_values("travel_s").drop_duplicates(["src", "dst"], keep="first")
e.to_csv(PROC / "b2_roads.csv", index=False)
print(f"before SCC: nodes={n0} edges={e0}; after SCC: nodes={n1} edges={e1}; "
      f"csv edges after parallel dedupe={len(e)} (dropped {m0 - len(e)})")
