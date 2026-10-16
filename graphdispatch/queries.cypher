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

-- [load_roads] Batch-merge directed ROAD edges (skipping pairs that are currently closed, so a restart never undoes a closure).
UNWIND $rows AS r MATCH (a:Intersection {osm_id: r.src}), (b:Intersection {osm_id: r.dst}) WHERE NOT (a)-[:CLOSED_ROAD]->(b) MERGE (a)-[e:ROAD]->(b) SET e.travel_s = r.travel_s, e.length_m = r.length_m, e.name = r.name;

-- [load_capabilities] Merge capability vocabulary nodes.
UNWIND $names AS n MERGE (:Capability {name: n});

-- [load_stations] Merge stations.
UNWIND $rows AS r MERGE (s:Station {station_id: r.station_id}) SET s.name = r.name, s.agency = r.agency, s.osm_id = r.osm_id;

-- [load_hospitals] Merge hospitals (matched by osm_id, never by name).
UNWIND $rows AS r MERGE (h:Hospital {osm_id: r.osm_id}) SET h.name = r.name, h.source = r.source, h.source_date = r.source_date;

-- [load_offers] Link hospitals to the capabilities they offer, with an optional designation level.
UNWIND $rows AS r MATCH (h:Hospital {osm_id: r.osm_id}), (c:Capability {name: r.cap}) MERGE (h)-[o:OFFERS]->(c) SET o.level = r.level;

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

-- [unit_candidates] Multi-hop: required capabilities to available units, their station and station intersection.
MATCH (c:Capability)<-[:HAS_CAPABILITY]-(u:Unit {status: 'available'})-[:BASED_AT]->(s:Station)-[:LOCATED_AT]->(i:Intersection) WHERE c.name IN $caps RETURN c.name AS cap, u.unit_id AS unit_id, s.station_id AS station_id, i.osm_id AS node ORDER BY cap, unit_id;

-- [required_caps] Capabilities (with counts) an incident type requires, including those no available unit has.
MATCH (t:IncidentType {name: $name})-[q:REQUIRES]->(c:Capability) RETURN c.name AS cap, q.count AS need ORDER BY cap;

-- [dest_capability] Destination capability and optional fallback rule for an incident type (no row if none).
MATCH (t:IncidentType {name: $name})-[e:DESTINATION_NEEDS]->(c:Capability) RETURN c.name AS cap, e.fallback AS fallback, e.max_extra_s AS max_extra_s, e.max_total_s AS max_total_s, e.source AS source;

-- [hospitals] Every hospital with its intersection, offered capabilities and designation levels.
MATCH (h:Hospital)-[:LOCATED_AT]->(i:Intersection) OPTIONAL MATCH (h)-[o:OFFERS]->(c:Capability) RETURN h.osm_id AS osm_id, h.name AS name, i.osm_id AS node, collect(c.name) AS caps, collect({cap: c.name, level: o.level}) AS offers ORDER BY osm_id;

-- [eta] Travel time in seconds along the cheapest outgoing path between two intersections via SPpaths.
MATCH (a:Intersection {osm_id: $src}), (b:Intersection {osm_id: $dst}) CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['ROAD'], relDirection: 'outgoing', weightProp: 'travel_s', pathCount: 1}) YIELD pathWeight RETURN pathWeight;

-- [route] Cheapest outgoing path between two intersections via SPpaths: weight and ordered node ids.
MATCH (a:Intersection {osm_id: $src}), (b:Intersection {osm_id: $dst}) CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['ROAD'], relDirection: 'outgoing', weightProp: 'travel_s', pathCount: 1}) YIELD path, pathWeight RETURN pathWeight, [n IN nodes(path) | n.osm_id] AS nodes;

-- [create_incident] Create a synthetic incident with its caller, address and nearest intersection (call_text and intake_model are set only for LLM intake).
MERGE (c:Caller {caller_id: $caller_id}) MERGE (a:Address {address_id: $address_id}) ON CREATE SET a.label = $label, a.lat = $lat, a.lon = $lon WITH c, a MATCH (t:IncidentType {name: $type}), (i:Intersection {osm_id: $node}) CREATE (inc:Incident {incident_id: $incident_id, type: $type, lat: $lat, lon: $lon, created_at: $now, created_ns: $created_ns, status: 'open', synthetic: true, call_text: $call_text, intake_model: $intake_model}) CREATE (inc)-[:OF_TYPE]->(t), (inc)-[:AT]->(a), (inc)-[:NEAREST]->(i), (c)-[:CALLED_ABOUT {at: $now}]->(inc) RETURN inc.incident_id;

-- [incident_info] Incident status, type and address.
MATCH (inc:Incident {incident_id: $incident_id})-[:AT]->(a:Address) RETURN inc.incident_id AS incident_id, inc.type AS type, inc.status AS status, inc.lat AS lat, inc.lon AS lon, inc.created_at AS created_at, a.address_id AS address_id, a.label AS label;

-- [recall_incidents] Earlier incidents at the same address since a cutoff time.
MATCH (inc:Incident {incident_id: $incident_id})-[:AT]->(a:Address)<-[:AT]-(p:Incident) WHERE p.incident_id <> $incident_id AND (p.created_at < inc.created_at OR (p.created_at = inc.created_at AND p.created_ns < inc.created_ns)) AND p.created_at >= $since RETURN p.incident_id AS incident_id, p.type AS type, p.created_at AS created_at, p.status AS status ORDER BY p.created_at, p.created_ns;

-- [recall_hazards] Hazards at the incident's address that are valid at the given time, with the kind's crew note.
MATCH (inc:Incident {incident_id: $incident_id})-[:AT]->(a:Address)<-[:AT]-(h:Hazard) OPTIONAL MATCH (h)-[:OF_KIND]->(k:HazardKind) WITH h, k WHERE h.valid_from <= $now AND $now <= h.valid_to RETURN h.hazard_id AS hazard_id, h.kind AS kind, h.note AS note, h.valid_from AS valid_from, h.valid_to AS valid_to, k.crew_note AS crew_note, h.reported_by AS reported_by ORDER BY h.created_at, h.created_ns;

-- [add_hazard] Create a hazard of a known kind at an address (address created with label, and position when given).
MATCH (k:HazardKind {name: $kind}) MERGE (a:Address {address_id: $address_id}) ON CREATE SET a.label = $label, a.lat = $lat, a.lon = $lon CREATE (h:Hazard {hazard_id: $hazard_id, kind: $kind, note: $note, valid_from: $valid_from, valid_to: $valid_to, created_at: $now, created_ns: $created_ns, reported_by: $reported_by}) CREATE (h)-[:AT]->(a), (h)-[:OF_KIND]->(k) RETURN h.hazard_id;

-- [hazard_reported_in] Link a hazard to the incident it was reported in.
MATCH (h:Hazard {hazard_id: $hazard_id}), (inc:Incident {incident_id: $incident_id}) CREATE (h)-[:REPORTED_IN]->(inc);

-- [decision_create] Create a decision node for an incident, with unmet capabilities, closure effects (changes) and legs with no route.
MATCH (inc:Incident {incident_id: $incident_id}) CREATE (d:Decision {decision_id: $decision_id, ts: $ts, agent: 'deterministic-v1', rule_applied: $rule_applied, unmet: $unmet, unmet_reasons: $unmet_reasons, changes: $changes, no_route: $no_route}) CREATE (d)-[:FOR]->(inc);

-- [decision_considered] Record candidate units considered, with capability, ETA and rank.
UNWIND $rows AS r MATCH (d:Decision {decision_id: $decision_id}), (u:Unit {unit_id: r.unit_id}) CREATE (d)-[:CONSIDERED {capability: r.capability, eta_s: r.eta_s, rank: r.rank}]->(u);

-- [decision_chose] Record chosen units with the capability they cover, ETA and why the capability was required.
UNWIND $rows AS r MATCH (d:Decision {decision_id: $decision_id}), (u:Unit {unit_id: r.unit_id}) CREATE (d)-[:CHOSE {capability: r.capability, eta_s: r.eta_s, reason: r.reason}]->(u);

-- [decision_destination] Record the chosen destination hospital, ETA and designation level.
MATCH (d:Decision {decision_id: $decision_id}), (h:Hospital {osm_id: $osm_id}) CREATE (d)-[:DESTINATION {eta_s: $eta_s, level: $level}]->(h);

-- [decision_skipped] Record hospitals skipped, with reason and ETA.
UNWIND $rows AS r MATCH (d:Decision {decision_id: $decision_id}), (h:Hospital {osm_id: r.osm_id}) CREATE (d)-[:SKIPPED {reason: r.reason, eta_s: r.eta_s}]->(h);

-- [decision_route] Record route path nodes per leg in order.
UNWIND $rows AS r MATCH (d:Decision {decision_id: $decision_id}), (i:Intersection {osm_id: r.node}) CREATE (d)-[:ROUTE {leg: r.leg, seq: r.seq}]->(i);

-- [decision_recalled_hazards] Record hazards surfaced to this decision.
UNWIND $ids AS id MATCH (d:Decision {decision_id: $decision_id}), (h:Hazard {hazard_id: id}) CREATE (d)-[:RECALLED]->(h);

-- [decision_recalled_incidents] Record earlier incidents surfaced to this decision.
UNWIND $ids AS id MATCH (d:Decision {decision_id: $decision_id}), (p:Incident {incident_id: id}) CREATE (d)-[:RECALLED]->(p);

-- [why] Everything recorded for one decision, in a single query.
MATCH (d:Decision {decision_id: $decision_id})-[:FOR]->(inc:Incident)-[:AT]->(a:Address) OPTIONAL MATCH (d)-[r1:CONSIDERED]->(u1:Unit) WITH d, inc, a, collect({unit_id: u1.unit_id, capability: r1.capability, eta_s: r1.eta_s, rank: r1.rank}) AS considered OPTIONAL MATCH (d)-[r2:CHOSE]->(u2:Unit) WITH d, inc, a, considered, collect({unit_id: u2.unit_id, capability: r2.capability, eta_s: r2.eta_s, reason: r2.reason}) AS chose OPTIONAL MATCH (d)-[r3:DESTINATION]->(h3:Hospital) WITH d, inc, a, considered, chose, collect({osm_id: h3.osm_id, name: h3.name, eta_s: r3.eta_s, level: r3.level}) AS destination OPTIONAL MATCH (d)-[r4:SKIPPED]->(h4:Hospital) WITH d, inc, a, considered, chose, destination, collect({osm_id: h4.osm_id, name: h4.name, eta_s: r4.eta_s, reason: r4.reason}) AS skipped OPTIONAL MATCH (d)-[r5:ROUTE]->(i5:Intersection) WITH d, inc, a, considered, chose, destination, skipped, collect({leg: r5.leg, seq: r5.seq, node: i5.osm_id, lat: i5.lat, lon: i5.lon}) AS route OPTIONAL MATCH (d)-[:RECALLED]->(h6:Hazard) OPTIONAL MATCH (h6)-[:OF_KIND]->(k6:HazardKind) WITH d, inc, a, considered, chose, destination, skipped, route, collect({hazard_id: h6.hazard_id, kind: h6.kind, note: h6.note, crew_note: k6.crew_note, created_ns: h6.created_ns}) AS recalled_hazards OPTIONAL MATCH (d)-[:RECALLED]->(p7:Incident) WITH d, inc, a, considered, chose, destination, skipped, route, recalled_hazards, collect({incident_id: p7.incident_id, type: p7.type}) AS recalled_incidents OPTIONAL MATCH (d)-[rr:REROUTED_AROUND]->(cl:Closure) WITH d, inc, a, considered, chose, destination, skipped, route, recalled_hazards, recalled_incidents, collect({leg: rr.leg, extra_s: rr.extra_s, closure_id: cl.closure_id, name: cl.name, reason: cl.reason}) AS rerouted RETURN d.decision_id AS decision_id, d.ts AS ts, d.agent AS agent, d.rule_applied AS rule_applied, inc.incident_id AS incident_id, inc.type AS type, inc.status AS status, a.label AS address, considered, chose, destination, skipped, route, recalled_hazards, recalled_incidents, d.unmet AS unmet, d.unmet_reasons AS unmet_reasons, rerouted, d.changes AS changes, d.no_route AS no_route;

-- [decision_units] Units chosen by a decision with their current status.
MATCH (d:Decision {decision_id: $decision_id})-[:CHOSE]->(u:Unit) RETURN u.unit_id AS unit_id, u.status AS status ORDER BY unit_id;

-- [dispatch] All-or-nothing dispatch: assign the chosen units and mark the incident dispatched only if every chosen unit is available.
MATCH (d:Decision {decision_id: $decision_id})-[:FOR]->(inc:Incident) MATCH (d)-[:CHOSE]->(u:Unit) WITH inc, collect(u) AS units WHERE size(units) > 0 AND all(x IN units WHERE x.status = 'available') UNWIND units AS x SET x.status = 'assigned' MERGE (x)-[:ASSIGNED_TO]->(inc) WITH inc, count(x) AS n SET inc.status = 'dispatched' RETURN n;

-- [clear] Return an incident's assigned units to available and mark the incident cleared.
MATCH (inc:Incident {incident_id: $incident_id}) OPTIONAL MATCH (u:Unit)-[r:ASSIGNED_TO]->(inc) WITH inc, collect(u) AS units, collect(r) AS rels FOREACH (x IN units | SET x.status = 'available') FOREACH (e IN rels | DELETE e) SET inc.status = 'cleared' RETURN size(units) AS n;

-- [set_unit_status] Administrative/test helper: set one unit's status.
MATCH (u:Unit {unit_id: $unit_id}) SET u.status = $status;

-- [wipe_runtime] Test helper: delete all runtime nodes (incidents, callers, addresses, hazards, decisions, closures). Reopen closures first so no road stays closed.
MATCH (n) WHERE n:Incident OR n:Caller OR n:Address OR n:Hazard OR n:Decision OR n:Closure DETACH DELETE n;

-- [unit_statuses] Every unit with its current status.
MATCH (u:Unit) RETURN u.unit_id AS unit_id, u.status AS status ORDER BY unit_id;

-- [assigned_to_count] Number of ASSIGNED_TO relationships (test helper).
MATCH ()-[r:ASSIGNED_TO]->() RETURN count(r);

-- [idx_hazard_kind] Index HazardKind.name.
CREATE INDEX FOR (n:HazardKind) ON (n.name);

-- [load_hazard_kinds] Merge synthetic hazard kinds with their crew notes.
UNWIND $rows AS r MERGE (k:HazardKind {name: r.kind}) SET k.crew_note = r.crew_note, k.synthetic = true;

-- [load_hazard_adds] Link hazard kinds to capabilities they add for an incident type.
UNWIND $rows AS r MATCH (k:HazardKind {name: r.kind}), (c:Capability {name: r.cap}) MERGE (k)-[a:ADDS_REQUIREMENT {incident_type: r.incident_type}]->(c) SET a.count = r.count;

-- [hazard_kinds] List allowed hazard kinds.
MATCH (k:HazardKind) RETURN k.name AS name ORDER BY name;

-- [effective_requirements] Incident type requirements plus requirements added by active hazards at the incident's address; hazards are grouped by (capability, kind) taking the max count per kind, so repeated hazards of one kind never double count.
MATCH (inc:Incident {incident_id: $incident_id})-[:OF_TYPE]->(t:IncidentType) OPTIONAL MATCH (t)-[q:REQUIRES]->(c1:Capability) WITH inc, t, collect({cap: c1.name, need: q.count, source: 'base'}) AS base OPTIONAL MATCH (inc)-[:AT]->(:Address)<-[:AT]-(h:Hazard)-[:OF_KIND]->(k:HazardKind)-[r:ADDS_REQUIREMENT]->(c2:Capability) WHERE h.valid_from <= $now AND $now <= h.valid_to AND r.incident_type = t.name WITH base, c2.name AS cap, k.name AS kind, max(r.count) AS need, collect(h.hazard_id) AS ids WITH base, collect({cap: cap, need: need, source: 'hazard:' + reduce(acc = '', i IN ids | CASE WHEN acc = '' THEN i ELSE acc + ',' + i END) + ':' + kind}) AS added UNWIND base + added AS x WITH x WHERE x.cap IS NOT NULL RETURN x.cap AS cap, sum(x.need) AS need, collect(x.source) AS sources ORDER BY cap;

-- [runtime_label_counts] Node counts for runtime labels only (reset dry run).
MATCH (n) WHERE n:Incident OR n:Decision OR n:Caller OR n:Address OR n:Hazard OR n:Closure RETURN labels(n)[0] AS label, count(n) AS c ORDER BY label;

-- [runtime_rel_counts] Relationship counts for relationships touching runtime labels (reset dry run).
MATCH (a)-[r]->(b) WHERE a:Incident OR a:Decision OR a:Caller OR a:Address OR a:Hazard OR a:Closure OR b:Incident OR b:Decision OR b:Caller OR b:Address OR b:Hazard OR b:Closure OR type(r) = 'CLOSED_ROAD' RETURN type(r) AS t, count(r) AS c ORDER BY t;

-- [seed_label_counts] Node counts for non-runtime (seed) labels.
MATCH (n) WHERE NOT (n:Incident OR n:Decision OR n:Caller OR n:Address OR n:Hazard OR n:Closure) RETURN labels(n)[0] AS label, count(n) AS c ORDER BY label;

-- [seed_rel_counts] Relationship counts for relationships between seed labels only.
MATCH (a)-[r]->(b) WHERE NOT (a:Incident OR a:Decision OR a:Caller OR a:Address OR a:Hazard OR a:Closure OR b:Incident OR b:Decision OR b:Caller OR b:Address OR b:Hazard OR b:Closure OR type(r) = 'CLOSED_ROAD') RETURN type(r) AS t, count(r) AS c ORDER BY t;

-- [incident_type_names] List incident type names (enum source for LLM tools).
MATCH (t:IncidentType) RETURN t.name AS name ORDER BY name;

-- [address_hazards] Active hazards at an address (by normalized address_id) with crew notes.
MATCH (a:Address {address_id: $address_id})<-[:AT]-(h:Hazard) WHERE h.valid_from <= $now AND $now <= h.valid_to OPTIONAL MATCH (h)-[:OF_KIND]->(k:HazardKind) RETURN h.hazard_id AS hazard_id, h.kind AS kind, h.note AS note, h.valid_to AS valid_to, k.crew_note AS crew_note ORDER BY h.created_at, h.created_ns;

-- [address_incidents] Incidents at an address (by normalized address_id) created since a cutoff time.
MATCH (a:Address {address_id: $address_id})<-[:AT]-(p:Incident) WHERE p.created_at >= $since RETURN p.incident_id AS incident_id, p.type AS type, p.status AS status, p.created_at AS created_at ORDER BY p.created_at, p.incident_id;

-- [open_incidents] Incidents that are open or dispatched, with their address.
MATCH (inc:Incident)-[:AT]->(a:Address) WHERE inc.status IN ['open', 'dispatched'] RETURN inc.incident_id AS incident_id, inc.type AS type, inc.status AS status, inc.created_at AS created_at, a.label AS address ORDER BY inc.created_at, inc.incident_id;

-- [unit_status_detail] Every unit with type, status and station.
MATCH (u:Unit)-[:BASED_AT]->(s:Station) RETURN u.unit_id AS unit_id, u.type AS type, u.status AS status, s.station_id AS station_id ORDER BY unit_id;

-- [health_ping] Health check: count intersections (a real graph read).
MATCH (i:Intersection) RETURN count(i) AS intersections;

-- [meta_stations] Stations with the position of the intersection they snap to.
MATCH (s:Station)-[:LOCATED_AT]->(i:Intersection) RETURN s.station_id AS station_id, s.name AS name, s.agency AS agency, i.lat AS lat, i.lon AS lon ORDER BY station_id;

-- [meta_hospitals] Hospitals with snapped position, offered capabilities and designation levels.
MATCH (h:Hospital)-[:LOCATED_AT]->(i:Intersection) OPTIONAL MATCH (h)-[o:OFFERS]->(c:Capability) RETURN h.osm_id AS osm_id, h.name AS name, i.lat AS lat, i.lon AS lon, collect({cap: c.name, level: o.level}) AS offers ORDER BY osm_id;

-- [active_hazards_map] Active hazards with the address position and crew note (for map markers).
MATCH (h:Hazard)-[:AT]->(a:Address) WHERE h.valid_from <= $now AND $now <= h.valid_to AND a.lat IS NOT NULL OPTIONAL MATCH (h)-[:OF_KIND]->(k:HazardKind) RETURN h.hazard_id AS hazard_id, h.kind AS kind, h.note AS note, a.label AS address, a.lat AS lat, a.lon AS lon, k.crew_note AS crew_note ORDER BY h.created_ns;

-- [expire_incidents] Demo self-healing: expire open or dispatched incidents created before a cutoff and free the units assigned to them (decisions and hazards are kept).
MATCH (inc:Incident) WHERE inc.status IN ['open', 'dispatched'] AND inc.created_at < $cutoff OPTIONAL MATCH (u:Unit)-[r:ASSIGNED_TO]->(inc) WITH inc, collect(u) AS units, collect(r) AS rels FOREACH (x IN units | SET x.status = 'available') FOREACH (e IN rels | DELETE e) SET inc.status = 'expired' RETURN count(inc) AS expired, sum(size(units)) AS units_freed;

-- [idx_closure] Index Closure.closure_id.
CREATE INDEX FOR (n:Closure) ON (n.closure_id);

-- [close_road] Close a road: retype the ROAD edges between two intersections (both directions where they exist) to CLOSED_ROAD with the same properties plus closure_id, and create the Closure node.
MATCH (a:Intersection {osm_id: $src}), (b:Intersection {osm_id: $dst}) OPTIONAL MATCH (a)-[f:ROAD]->(b) OPTIONAL MATCH (b)-[r:ROAD]->(a) WITH a, b, f, r WHERE f IS NOT NULL OR r IS NOT NULL CREATE (c:Closure {closure_id: $closure_id, reason: $reason, closed_at: $now, expires_at: $expires, src_osm: $src, dst_osm: $dst, name: coalesce(f.name, r.name, ''), synthetic: true}) CREATE (c)-[:AT]->(a), (c)-[:AT]->(b) FOREACH (e IN CASE WHEN f IS NULL THEN [] ELSE [f] END | CREATE (a)-[:CLOSED_ROAD {travel_s: e.travel_s, length_m: e.length_m, name: e.name, closure_id: $closure_id}]->(b)) FOREACH (e IN CASE WHEN r IS NULL THEN [] ELSE [r] END | CREATE (b)-[:CLOSED_ROAD {travel_s: e.travel_s, length_m: e.length_m, name: e.name, closure_id: $closure_id}]->(a)) FOREACH (e IN CASE WHEN f IS NULL THEN [] ELSE [f] END | DELETE e) FOREACH (e IN CASE WHEN r IS NULL THEN [] ELSE [r] END | DELETE e) RETURN c.closure_id AS id;

-- [reopen_road] Reopen a closed road: retype its CLOSED_ROAD edges back to ROAD with the original travel_s, length_m and name, and mark the Closure reopened (it is kept for provenance).
MATCH (c:Closure {closure_id: $closure_id}) WHERE c.reopened_at IS NULL MATCH (a:Intersection {osm_id: c.src_osm}), (b:Intersection {osm_id: c.dst_osm}) OPTIONAL MATCH (a)-[f:CLOSED_ROAD {closure_id: $closure_id}]->(b) OPTIONAL MATCH (b)-[r:CLOSED_ROAD {closure_id: $closure_id}]->(a) FOREACH (e IN CASE WHEN f IS NULL THEN [] ELSE [f] END | CREATE (a)-[:ROAD {travel_s: e.travel_s, length_m: e.length_m, name: e.name}]->(b)) FOREACH (e IN CASE WHEN r IS NULL THEN [] ELSE [r] END | CREATE (b)-[:ROAD {travel_s: e.travel_s, length_m: e.length_m, name: e.name}]->(a)) FOREACH (e IN CASE WHEN f IS NULL THEN [] ELSE [f] END | DELETE e) FOREACH (e IN CASE WHEN r IS NULL THEN [] ELSE [r] END | DELETE e) SET c.reopened_at = $now RETURN c.closure_id AS id;

-- [closures_list] Active closures (not yet reopened) with the coordinates of both ends.
MATCH (c:Closure) WHERE c.reopened_at IS NULL MATCH (a:Intersection {osm_id: c.src_osm}), (b:Intersection {osm_id: c.dst_osm}) RETURN c.closure_id AS closure_id, c.reason AS reason, c.name AS name, c.closed_at AS closed_at, c.expires_at AS expires_at, c.src_osm AS src_osm, c.dst_osm AS dst_osm, a.lat AS a_lat, a.lon AS a_lon, b.lat AS b_lat, b.lon AS b_lon ORDER BY c.closed_at, c.closure_id;

-- [active_closure_count] Number of active (not reopened) closures.
MATCH (c:Closure) WHERE c.reopened_at IS NULL RETURN count(c) AS n;

-- [expired_closures] Ids of active closures whose expiry time has passed.
MATCH (c:Closure) WHERE c.reopened_at IS NULL AND c.expires_at <= $now RETURN c.closure_id AS closure_id ORDER BY c.expires_at;

-- [nearest_road_segment] The open ROAD segment whose midpoint is nearest to a point (distance from the intersection coordinates).
MATCH (a:Intersection)-[r:ROAD]->(b:Intersection) WITH a, b, r, distance(point({latitude: (a.lat + b.lat) / 2, longitude: (a.lon + b.lon) / 2}), point({latitude: $lat, longitude: $lon})) AS d ORDER BY d LIMIT 1 RETURN a.osm_id AS src, b.osm_id AS dst, r.name AS name, d AS dist_m;

-- [eta_all] Travel time ignoring closures: cheapest path over ROAD and CLOSED_ROAD (used to show what a closure cost).
MATCH (a:Intersection {osm_id: $src}), (b:Intersection {osm_id: $dst}) CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['ROAD', 'CLOSED_ROAD'], relDirection: 'outgoing', weightProp: 'travel_s', pathCount: 1}) YIELD path, pathWeight RETURN pathWeight;

-- [route_all] Cheapest path over ROAD and CLOSED_ROAD: weight, ordered node ids and the closure ids it passes through (empty when no closed road is on it).
MATCH (a:Intersection {osm_id: $src}), (b:Intersection {osm_id: $dst}) CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['ROAD', 'CLOSED_ROAD'], relDirection: 'outgoing', weightProp: 'travel_s', pathCount: 1}) YIELD path, pathWeight RETURN pathWeight, [n IN nodes(path) | n.osm_id] AS nodes, [r IN relationships(path) WHERE type(r) = 'CLOSED_ROAD' | r.closure_id] AS closed;

-- [decision_rerouted] Record, per leg, the closure a decision had to route around and the extra seconds it cost.
UNWIND $rows AS r MATCH (d:Decision {decision_id: $decision_id}), (c:Closure {closure_id: r.closure_id}) CREATE (d)-[:REROUTED_AROUND {leg: r.leg, extra_s: r.extra_s}]->(c);
