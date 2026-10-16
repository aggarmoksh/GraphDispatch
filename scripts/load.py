"""Idempotent loader for the graph named by GRAPH_NAME (default sjfd). Reads ONLY from seed/.

Usage: python scripts/load.py [--counts]
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from graphdispatch import db  # noqa: E402

SEED = ROOT / "seed"
B = 500
INDEXES = ["idx_intersection", "idx_unit", "idx_station", "idx_hospital", "idx_capability", "idx_incident_type",
           "idx_incident", "idx_address", "idx_caller", "idx_hazard", "idx_decision"]


def snapshot_dir():
    return sorted(SEED.glob("osm_b2_*"))[-1]


def batches(rows):
    for i in range(0, len(rows), B):
        yield rows[i:i + B]


def split(v):
    return [x for x in str(v).split(";") if x] if isinstance(v, str) else []


def counts():
    return ({r[0]: r[1] for r in db.read("count_labels")}, {r[0]: r[1] for r in db.read("count_rels")})


def _units():
    units = pd.read_csv(SEED / "units.csv", comment="#")
    return [dict(unit_id=r.unit_id, type=r.type, status=r.status, station_id=int(r.station_id))
            for r in units.itertuples()]


def reset_units():
    """Reset every unit's status to the seed value (test graphs only)."""
    db.write("load_units", {"rows": _units()})


def load():
    for ix in INDEXES:
        try:
            db.write(ix)
        except Exception as e:
            if "already indexed" not in str(e).lower():
                raise
    snap = snapshot_dir()
    nodes = pd.read_csv(snap / "b2_intersections.csv").to_dict("records")
    roads = pd.read_csv(snap / "b2_roads.csv", keep_default_na=False).to_dict("records")
    for b in batches(nodes):
        db.write("load_intersections", {"rows": b})
    for b in batches(roads):
        db.write("load_roads", {"rows": b})

    hosp = pd.read_csv(SEED / "hospitals.csv", comment="#", dtype={"osm_id": int})
    stations = pd.read_csv(SEED / "stations.csv", comment="#")
    units = pd.read_csv(SEED / "units.csv", comment="#")
    itypes = pd.read_csv(SEED / "incident_types.csv", comment="#", dtype=str).fillna("")

    caps = set()
    for c in list(hosp.capabilities) + list(units.capabilities):
        caps.update(split(c))
    for r in itypes.itertuples():
        caps.update(x.split(":")[0] for x in split(r.requires))
        if r.destination_capability:
            caps.add(r.destination_capability)
        if r.fallback_capability:
            caps.add(r.fallback_capability)
    db.write("load_capabilities", {"names": sorted(caps)})

    db.write("load_stations", {"rows": [dict(osm_id=int(r.osm_id), station_id=int(r.station_id), name=r.name, agency=r.agency)
                                        for r in stations.itertuples()]})
    db.write("load_hospitals", {"rows": [dict(osm_id=int(r.osm_id), name=r.name, source=r.source, source_date=r.source_date)
                                         for r in hosp.itertuples()]})
    db.write("load_offers", {"rows": [dict(osm_id=int(r.osm_id), cap=c) for r in hosp.itertuples() for c in split(r.capabilities)]})
    db.write("load_units", {"rows": _units()})
    db.write("load_unit_caps", {"rows": [dict(unit_id=r.unit_id, cap=c) for r in units.itertuples() for c in split(r.capabilities)]})
    db.write("load_incident_types", {"names": list(itypes.name)})
    db.write("load_requires", {"rows": [dict(name=r.name, cap=x.split(":")[0], count=int(x.split(":")[1]))
                                        for r in itypes.itertuples() for x in split(r.requires)]})
    db.write("load_dest_needs", {"rows": [
        dict(name=r.name, cap=r.destination_capability,
             fallback=r.fallback_capability or None,
             max_extra_s=int(r.max_extra_s) if r.max_extra_s else None,
             max_total_s=int(r.max_total_s) if r.max_total_s else None,
             source=r.rule_source or None)
        for r in itypes.itertuples() if r.destination_capability]})
    for r in stations.itertuples():
        db.write("snap_station", {"id": int(r.station_id), "lat": float(r.lat), "lon": float(r.lon)})
    for r in hosp.itertuples():
        db.write("snap_hospital", {"id": int(r.osm_id), "lat": float(r.lat), "lon": float(r.lon)})


def main():
    if "--counts" not in sys.argv:
        load()
    print(f"graph={db.graph_name()}")
    print(counts())
    for row in db.read("snap_report"):
        print(row)


if __name__ == "__main__":
    main()
