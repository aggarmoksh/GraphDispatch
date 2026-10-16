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

-- [idx_incident] Index Incident.incident_id.
CREATE INDEX FOR (n:Incident) ON (n.incident_id);

-- [idx_address] Index Address.address_id.
CREATE INDEX FOR (n:Address) ON (n.address_id);

-- [idx_caller] Index Caller.caller_id.
CREATE INDEX FOR (n:Caller) ON (n.caller_id);

-- [idx_hazard] Index Hazard.hazard_id.
CREATE INDEX FOR (n:Hazard) ON (n.hazard_id);

-- [idx_decision] Index Decision.decision_id.
CREATE INDEX FOR (n:Decision) ON (n.decision_id);

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

-- [load_dest_needs] Link incident types to the destination capability, with optional bypass-rule properties (null props are skipped).
UNWIND $rows AS r MATCH (t:IncidentType {name: r.name}), (c:Capability {name: r.cap}) MERGE (t)-[e:DESTINATION_NEEDS]->(c) SET e.fallback = r.fallback, e.max_extra_s = r.max_extra_s, e.max_total_s = r.max_total_s, e.source = r.source;

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

-- [dest_capability] Destination capability and optional fallback rule for an incident type (no row if none).
MATCH (t:IncidentType {name: $name})-[e:DESTINATION_NEEDS]->(c:Capability) RETURN c.name AS cap, e.fallback AS fallback, e.max_extra_s AS max_extra_s, e.max_total_s AS max_total_s, e.source AS source;

-- [hospitals] Every hospital with its intersection and offered capabilities.
MATCH (h:Hospital)-[:LOCATED_AT]->(i:Intersection) OPTIONAL MATCH (h)-[:OFFERS]->(c:Capability) RETURN h.osm_id AS osm_id, h.name AS name, i.osm_id AS node, collect(c.name) AS caps ORDER BY osm_id;

-- [eta] Travel time in seconds along the cheapest outgoing path between two intersections via SPpaths.
MATCH (a:Intersection {osm_id: $src}), (b:Intersection {osm_id: $dst}) CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['ROAD'], relDirection: 'outgoing', weightProp: 'travel_s', pathCount: 1}) YIELD pathWeight RETURN pathWeight;

-- [route] Cheapest outgoing path between two intersections via SPpaths: weight and ordered node ids.
MATCH (a:Intersection {osm_id: $src}), (b:Intersection {osm_id: $dst}) CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['ROAD'], relDirection: 'outgoing', weightProp: 'travel_s', pathCount: 1}) YIELD path, pathWeight RETURN pathWeight, [n IN nodes(path) | n.osm_id] AS nodes;

-- [create_incident] Create a synthetic incident with its caller, address and nearest intersection.
MERGE (c:Caller {caller_id: $caller_id}) MERGE (a:Address {address_id: $address_id}) ON CREATE SET a.label = $label, a.lat = $lat, a.lon = $lon WITH c, a MATCH (t:IncidentType {name: $type}), (i:Intersection {osm_id: $node}) CREATE (inc:Incident {incident_id: $incident_id, type: $type, lat: $lat, lon: $lon, created_at: $now, status: 'open', synthetic: true}) CREATE (inc)-[:OF_TYPE]->(t), (inc)-[:AT]->(a), (inc)-[:NEAREST]->(i), (c)-[:CALLED_ABOUT {at: $now}]->(inc) RETURN inc.incident_id;

-- [incident_info] Incident status, type and address.
MATCH (inc:Incident {incident_id: $incident_id})-[:AT]->(a:Address) RETURN inc.incident_id AS incident_id, inc.type AS type, inc.status AS status, inc.lat AS lat, inc.lon AS lon, inc.created_at AS created_at, a.address_id AS address_id, a.label AS label;

-- [recall_incidents] Earlier incidents at the same address since a cutoff time.
MATCH (inc:Incident {incident_id: $incident_id})-[:AT]->(a:Address)<-[:AT]-(p:Incident) WHERE p.incident_id <> $incident_id AND p.created_at < inc.created_at AND p.created_at >= $since RETURN p.incident_id AS incident_id, p.type AS type, p.created_at AS created_at, p.status AS status ORDER BY p.created_at, p.incident_id;

-- [recall_hazards] Hazards at the incident's address that are valid at the given time.
MATCH (inc:Incident {incident_id: $incident_id})-[:AT]->(a:Address)<-[:AT]-(h:Hazard) WHERE h.valid_from <= $now AND $now <= h.valid_to RETURN h.hazard_id AS hazard_id, h.kind AS kind, h.note AS note, h.valid_from AS valid_from, h.valid_to AS valid_to ORDER BY h.created_at, h.hazard_id;

-- [add_hazard] Create a hazard at an address (created if missing, label only).
MERGE (a:Address {address_id: $address_id}) ON CREATE SET a.label = $label CREATE (h:Hazard {hazard_id: $hazard_id, kind: $kind, note: $note, valid_from: $valid_from, valid_to: $valid_to, created_at: $now}) CREATE (h)-[:AT]->(a) RETURN h.hazard_id;

-- [hazard_reported_in] Link a hazard to the incident it was reported in.
MATCH (h:Hazard {hazard_id: $hazard_id}), (inc:Incident {incident_id: $incident_id}) CREATE (h)-[:REPORTED_IN]->(inc);

-- [decision_create] Create a decision node for an incident.
MATCH (inc:Incident {incident_id: $incident_id}) CREATE (d:Decision {decision_id: $decision_id, ts: $ts, agent: 'deterministic-v1', rule_applied: $rule_applied}) CREATE (d)-[:FOR]->(inc);

-- [decision_considered] Record candidate units considered, with capability, ETA and rank.
UNWIND $rows AS r MATCH (d:Decision {decision_id: $decision_id}), (u:Unit {unit_id: r.unit_id}) CREATE (d)-[:CONSIDERED {capability: r.capability, eta_s: r.eta_s, rank: r.rank}]->(u);

-- [decision_chose] Record chosen units with the capability they cover and ETA.
UNWIND $rows AS r MATCH (d:Decision {decision_id: $decision_id}), (u:Unit {unit_id: r.unit_id}) CREATE (d)-[:CHOSE {capability: r.capability, eta_s: r.eta_s}]->(u);

-- [decision_destination] Record the chosen destination hospital and ETA.
MATCH (d:Decision {decision_id: $decision_id}), (h:Hospital {osm_id: $osm_id}) CREATE (d)-[:DESTINATION {eta_s: $eta_s}]->(h);

-- [decision_skipped] Record hospitals skipped, with reason and ETA.
UNWIND $rows AS r MATCH (d:Decision {decision_id: $decision_id}), (h:Hospital {osm_id: r.osm_id}) CREATE (d)-[:SKIPPED {reason: r.reason, eta_s: r.eta_s}]->(h);

-- [decision_route] Record route path nodes per leg in order.
UNWIND $rows AS r MATCH (d:Decision {decision_id: $decision_id}), (i:Intersection {osm_id: r.node}) CREATE (d)-[:ROUTE {leg: r.leg, seq: r.seq}]->(i);

-- [decision_recalled_hazards] Record hazards surfaced to this decision.
UNWIND $ids AS id MATCH (d:Decision {decision_id: $decision_id}), (h:Hazard {hazard_id: id}) CREATE (d)-[:RECALLED]->(h);

-- [decision_recalled_incidents] Record earlier incidents surfaced to this decision.
UNWIND $ids AS id MATCH (d:Decision {decision_id: $decision_id}), (p:Incident {incident_id: id}) CREATE (d)-[:RECALLED]->(p);

-- [why] Everything recorded for one decision, in a single query.
MATCH (d:Decision {decision_id: $decision_id})-[:FOR]->(inc:Incident)-[:AT]->(a:Address) OPTIONAL MATCH (d)-[r1:CONSIDERED]->(u1:Unit) WITH d, inc, a, collect({unit_id: u1.unit_id, capability: r1.capability, eta_s: r1.eta_s, rank: r1.rank}) AS considered OPTIONAL MATCH (d)-[r2:CHOSE]->(u2:Unit) WITH d, inc, a, considered, collect({unit_id: u2.unit_id, capability: r2.capability, eta_s: r2.eta_s}) AS chose OPTIONAL MATCH (d)-[r3:DESTINATION]->(h3:Hospital) WITH d, inc, a, considered, chose, collect({osm_id: h3.osm_id, name: h3.name, eta_s: r3.eta_s}) AS destination OPTIONAL MATCH (d)-[r4:SKIPPED]->(h4:Hospital) WITH d, inc, a, considered, chose, destination, collect({osm_id: h4.osm_id, name: h4.name, eta_s: r4.eta_s, reason: r4.reason}) AS skipped OPTIONAL MATCH (d)-[r5:ROUTE]->(i5:Intersection) WITH d, inc, a, considered, chose, destination, skipped, collect({leg: r5.leg, seq: r5.seq, node: i5.osm_id}) AS route OPTIONAL MATCH (d)-[:RECALLED]->(h6:Hazard) WITH d, inc, a, considered, chose, destination, skipped, route, collect({hazard_id: h6.hazard_id, kind: h6.kind, note: h6.note}) AS recalled_hazards OPTIONAL MATCH (d)-[:RECALLED]->(p7:Incident) WITH d, inc, a, considered, chose, destination, skipped, route, recalled_hazards, collect({incident_id: p7.incident_id, type: p7.type}) AS recalled_incidents RETURN d.decision_id AS decision_id, d.ts AS ts, d.agent AS agent, d.rule_applied AS rule_applied, inc.incident_id AS incident_id, inc.type AS type, inc.status AS status, a.label AS address, considered, chose, destination, skipped, route, recalled_hazards, recalled_incidents;

-- [decision_units] Units chosen by a decision with their current status.
MATCH (d:Decision {decision_id: $decision_id})-[:CHOSE]->(u:Unit) RETURN u.unit_id AS unit_id, u.status AS status ORDER BY unit_id;

-- [dispatch] All-or-nothing dispatch: assign the chosen units and mark the incident dispatched only if every chosen unit is available.
MATCH (d:Decision {decision_id: $decision_id})-[:FOR]->(inc:Incident) MATCH (d)-[:CHOSE]->(u:Unit) WITH inc, collect(u) AS units WHERE size(units) > 0 AND all(x IN units WHERE x.status = 'available') UNWIND units AS x SET x.status = 'assigned' MERGE (x)-[:ASSIGNED_TO]->(inc) WITH inc, count(x) AS n SET inc.status = 'dispatched' RETURN n;

-- [clear] Return an incident's assigned units to available and mark the incident cleared.
MATCH (inc:Incident {incident_id: $incident_id}) OPTIONAL MATCH (u:Unit)-[r:ASSIGNED_TO]->(inc) WITH inc, collect(u) AS units, collect(r) AS rels FOREACH (x IN units | SET x.status = 'available') FOREACH (e IN rels | DELETE e) SET inc.status = 'cleared' RETURN size(units) AS n;

-- [set_unit_status] Administrative/test helper: set one unit's status.
MATCH (u:Unit {unit_id: $unit_id}) SET u.status = $status;

-- [wipe_runtime] Test helper: delete all runtime nodes (incidents, callers, addresses, hazards, decisions).
MATCH (n) WHERE n:Incident OR n:Caller OR n:Address OR n:Hazard OR n:Decision DETACH DELETE n;

-- [unit_statuses] Every unit with its current status.
MATCH (u:Unit) RETURN u.unit_id AS unit_id, u.status AS status ORDER BY unit_id;

-- [assigned_to_count] Number of ASSIGNED_TO relationships (test helper).
MATCH ()-[r:ASSIGNED_TO]->() RETURN count(r);
