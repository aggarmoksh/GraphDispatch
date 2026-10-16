# Seed data

## Attribution
Map data (c) OpenStreetMap contributors, ODbL. https://www.openstreetmap.org/copyright

## Snapshot
- `osm_b2_2026-10-15/`: OSM drive network for box B2 (W -121.945 S 37.300 E -121.840 N 37.370), downloaded 2026-10-15 with osmnx 2.1.1, largest strongly connected component only, parallel edges deduped to the smallest travel_s. This is the only road input `scripts/load.py` reads.
- `stations.csv`: SJFD station locations taken from OSM (positions only). Exclusions are in `EXCLUDED.md`.
- `hospitals.csv`: hospital positions from OSM; capabilities from the sources named per row. OSM operator tags are stale and not used.

## Synthetic (not real)
Units, incident types, callers, addresses, hazards and incidents are all synthetic. No phone numbers, real names or real emergency data are stored anywhere.

## Rules with sources
- Stroke destination rule: AHA Mission: Lifeline Stroke EMS triage algorithm (meded.stroke.org). A suspected LVO goes to an EVT-capable center if the extra transport time past the nearest stroke center is at most 30 min and the total at most 45 min (suburban numbers; the urban section gives none). Carried as properties on the stroke DESTINATION_NEEDS edge via `incident_types.csv`.

## Trauma levels
- CA EMSA "Designated Trauma Centers" list, updated 2025-08-25: Santa Clara Valley Medical Center is ACS adult Level I and ACS pediatric Level II; Regional Medical Center of San Jose is a local-designation adult Level II; O'Connor Hospital is not listed. Stored as `levels` in hospitals.csv and as OFFERS {level}.

## Hazard rules
- `hazard_rules.csv` is synthetic: hazard kinds, crew notes and the capabilities a kind adds to an incident type. Not real fire-code guidance.
