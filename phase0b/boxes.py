import osmnx as ox
import pandas as pd
from pathlib import Path

PROC = Path(__file__).resolve().parent.parent / "data/processed"
BOXES = {"B1": (-121.910, 37.320, -121.870, 37.350),
         "B2": (-121.945, 37.300, -121.840, 37.370),
         "B3": (-121.960, 37.240, -121.780, 37.400)}
hosp = pd.read_csv(PROC / "hospitals_raw.csv")
fire = pd.read_csv(PROC / "fire_stations_raw.csv")

def inside(df, b):
    w, s, e, n = b
    return df[(df.lon >= w) & (df.lon <= e) & (df.lat >= s) & (df.lat <= n)]

rows = []
for k, b in BOXES.items():
    G = ox.graph_from_bbox(b, network_type="drive")
    h = inside(hosp, b)
    rows.append(dict(box=k, west=b[0], south=b[1], east=b[2], north=b[3],
                     hospitals=len(h), hospitals_emergency_yes=int((h.emergency == "yes").sum()),
                     fire_stations=len(inside(fire, b)),
                     intersections=G.number_of_nodes(), edges=G.number_of_edges()))
    print(rows[-1])
pd.DataFrame(rows).to_csv(Path(__file__).with_name("boxes.csv"), index=False)
