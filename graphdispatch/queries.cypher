-- [idx_intersection] Index Intersection.osm_id.
CREATE INDEX FOR (n:Intersection) ON (n.osm_id);

-- [idx_unit] Index Unit.unit_id.
CREATE INDEX FOR (n:Unit) ON (n.unit_id);

-- [idx_station] Index Station.station_id.
CREATE INDEX FOR (n:Station) ON (n.station_id);

-- [idx_hospital] Index Hospital.osm_id.
CREATE INDEX FOR (n:Hospital) ON (n.osm_id);

-- [idx_capability] Index Capability.name.
CREATE INDEX FOR (n:Capability) ON (n.name);

-- [idx_incident_type] Index IncidentType.name.
CREATE INDEX FOR (n:IncidentType) ON (n.name);

-- [load_intersections] Batch-merge intersections with a geo point.
UNWIND $rows AS r MERGE (n:Intersection {osm_id: r.osm_id}) SET n.lat = r.lat, n.lon = r.lon, n.loc = point({latitude: r.lat, longitude: r.lon});

-- [load_roads] Batch-merge directed ROAD edges.
UNWIND $rows AS r MATCH (a:Intersection {osm_id: r.src}), (b:Intersection {osm_id: r.dst}) MERGE (a)-[e:ROAD]->(b) SET e.travel_s = r.travel_s, e.length_m = r.length_m, e.name = r.name;

-- [load_capabilities] Merge capability vocabulary nodes.
UNWIND $names AS n MERGE (:Capability {name: n});

-- [load_stations] Merge stations.
UNWIND $rows AS r MERGE (s:Station {station_id: r.station_id}) SET s.name = r.name, s.agency = r.agency, s.osm_id = r.osm_id;

-- [load_hospitals] Merge hospitals (matched by osm_id, never by name).
UNWIND $rows AS r MERGE (h:Hospital {osm_id: r.osm_id}) SET h.name = r.name, h.source = r.source, h.source_date = r.source_date;

-- [load_offers] Link hospitals to the capabilities they offer.
UNWIND $rows AS r MATCH (h:Hospital {osm_id: r.osm_id}), (c:Capability {name: r.cap}) MERGE (h)-[:OFFERS]->(c);

-- [load_units] Merge synthetic units and their base station.
UNWIND $rows AS r MATCH (s:Station {station_id: r.station_id}) MERGE (u:Unit {unit_id: r.unit_id}) SET u.type = r.type, u.status = r.status, u.synthetic = true MERGE (u)-[:BASED_AT]->(s);

-- [load_unit_caps] Link units to their capabilities.
UNWIND $rows AS r MATCH (u:Unit {unit_id: r.unit_id}), (c:Capability {name: r.cap}) MERGE (u)-[:HAS_CAPABILITY]->(c);

-- [load_incident_types] Merge synthetic incident types.
UNWIND $names AS n MERGE (t:IncidentType {name: n}) SET t.synthetic = true;

-- [load_requires] Link incident types to required capabilities with counts.
UNWIND $rows AS r MATCH (t:IncidentType {name: r.name}), (c:Capability {name: r.cap}) MERGE (t)-[q:REQUIRES]->(c) SET q.count = r.count;

-- [load_dest_needs] Link incident types to the capability a destination hospital needs.
UNWIND $rows AS r MATCH (t:IncidentType {name: r.name}), (c:Capability {name: r.cap}) MERGE (t)-[:DESTINATION_NEEDS]->(c);

-- [snap_station] Snap a station to its nearest intersection and store snap_m.
MATCH (s:Station {station_id: $id}) MATCH (i:Intersection) WITH s, i, distance(i.loc, point({latitude: $lat, longitude: $lon})) AS d ORDER BY d LIMIT 1 MERGE (s)-[l:LOCATED_AT]->(i) SET l.snap_m = d;

-- [snap_hospital] Snap a hospital to its nearest intersection and store snap_m.
MATCH (h:Hospital {osm_id: $id}) MATCH (i:Intersection) WITH h, i, distance(i.loc, point({latitude: $lat, longitude: $lon})) AS d ORDER BY d LIMIT 1 MERGE (h)-[l:LOCATED_AT]->(i) SET l.snap_m = d;

-- [count_labels] Node counts per label.
MATCH (n) RETURN labels(n)[0] AS label, count(n) AS c ORDER BY label;

-- [count_rels] Relationship counts per type.
MATCH ()-[r]->() RETURN type(r) AS t, count(r) AS c ORDER BY t;

-- [snap_report] Snap distances for every station and hospital.
MATCH (x)-[l:LOCATED_AT]->(i:Intersection) RETURN labels(x)[0] AS label, coalesce(x.station_id, x.osm_id) AS id, x.name AS name, l.snap_m AS snap_m ORDER BY label, id;

-- [snap_incident] Nearest intersection to an incident location and the snap distance in meters.
MATCH (i:Intersection) WITH i, distance(i.loc, point({latitude: $lat, longitude: $lon})) AS d ORDER BY d LIMIT 1 RETURN i.osm_id AS osm_id, d AS snap_m;

-- [unit_candidates] Multi-hop: incident type requirements to available units, their station and station intersection.
MATCH (t:IncidentType {name: $name})-[q:REQUIRES]->(c:Capability)<-[:HAS_CAPABILITY]-(u:Unit {status: 'available'})-[:BASED_AT]->(s:Station)-[:LOCATED_AT]->(i:Intersection) RETURN c.name AS cap, q.count AS need, u.unit_id AS unit_id, s.station_id AS station_id, i.osm_id AS node ORDER BY cap, unit_id;

-- [required_caps] Capabilities (with counts) an incident type requires, including those no available unit has.
MATCH (t:IncidentType {name: $name})-[q:REQUIRES]->(c:Capability) RETURN c.name AS cap, q.count AS need ORDER BY cap;

-- [dest_capability] Capability a destination hospital must offer for an incident type (no row if none).
MATCH (t:IncidentType {name: $name})-[:DESTINATION_NEEDS]->(c:Capability) RETURN c.name AS cap;

-- [hospitals] Every hospital with its intersection and offered capabilities.
MATCH (h:Hospital)-[:LOCATED_AT]->(i:Intersection) OPTIONAL MATCH (h)-[:OFFERS]->(c:Capability) RETURN h.osm_id AS osm_id, h.name AS name, i.osm_id AS node, collect(c.name) AS caps ORDER BY osm_id;

-- [eta] Travel time in seconds along the cheapest outgoing path between two intersections via SPpaths.
MATCH (a:Intersection {osm_id: $src}), (b:Intersection {osm_id: $dst}) CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['ROAD'], relDirection: 'outgoing', weightProp: 'travel_s', pathCount: 1}) YIELD pathWeight RETURN pathWeight;
