"""Fetch hospital and fire-station POIs from OSM (no filtering, no name edits)."""
import osmnx as ox
import pandas as pd
from pathlib import Path

PROC = Path(__file__).resolve().parents[3] / "data/processed"
PROC.mkdir(parents=True, exist_ok=True)
W, S, E, N = -121.960, 37.240, -121.780, 37.400
COLS = ["osm_id", "osm_type", "name", "lat", "lon", "emergency", "healthcare", "operator"]

def fetch(amenity, out):
    gdf = ox.features_from_bbox((W, S, E, N), tags={"amenity": amenity}).reset_index()
    cen = gdf.geometry.centroid
    df = pd.DataFrame({
        "osm_id": gdf["id"] if "id" in gdf else gdf["osmid"],
        "osm_type": gdf["element"] if "element" in gdf else gdf["element_type"],
        "name": gdf.get("name"), "lat": cen.y, "lon": cen.x,
        "emergency": gdf.get("emergency"), "healthcare": gdf.get("healthcare"),
        "operator": gdf.get("operator"),
    })[COLS]
    df.to_csv(PROC / out, index=False)
    print(amenity, len(df))

fetch("hospital", "hospitals_raw.csv")
fetch("fire_station", "fire_stations_raw.csv")
