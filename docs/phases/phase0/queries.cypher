-- [procedures] List all procedures the engine exposes.
CALL dbms.procedures();

-- [synth_node] Create one synthetic node.
CREATE (:Node {name: $name});

-- [synth_edge] Create one weighted ROAD edge between two synthetic nodes.
MATCH (a:Node {name: $src}), (b:Node {name: $dst}) CREATE (a)-[:ROAD {travel_s: $w}]->(b);

-- [synth_sp] Cheapest weighted path between two synthetic nodes via SPpaths.
MATCH (a:Node {name: $src}), (b:Node {name: $dst}) CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['ROAD'], relDirection: 'outgoing', weightProp: 'travel_s', pathCount: 1}) YIELD path, pathWeight RETURN [n IN nodes(path) | n.name] AS names, pathWeight, length(path) AS hops;

-- [road_index] Index Intersection(osm_id) before bulk load.
CREATE INDEX FOR (n:Intersection) ON (n.osm_id);

-- [load_nodes] Batch-merge intersections (idempotent).
UNWIND $rows AS r MERGE (n:Intersection {osm_id: r.osm_id}) SET n.lat = r.lat, n.lon = r.lon;

-- [load_edges] Batch-merge ROAD edges between intersections (idempotent).
UNWIND $rows AS r MATCH (a:Intersection {osm_id: r.src}), (b:Intersection {osm_id: r.dst}) MERGE (a)-[e:ROAD]->(b) SET e.travel_s = r.travel_s, e.length_m = r.length_m;

-- [count_nodes] Count intersections.
MATCH (n:Intersection) RETURN count(n);

-- [count_edges] Count ROAD edges.
MATCH ()-[e:ROAD]->() RETURN count(e);

-- [road_sp] Cheapest path between two intersections via SPpaths.
MATCH (a:Intersection {osm_id: $src}), (b:Intersection {osm_id: $dst}) CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['ROAD'], relDirection: 'outgoing', weightProp: 'travel_s', pathCount: 1}) YIELD path, pathWeight RETURN pathWeight, length(path) AS hops;

-- [road_astar] Same pair via algo.AStar (single config map; latitudeProperty/longitudeProperty required, verified on 4.22.1).
MATCH (a:Intersection {osm_id: $src}), (b:Intersection {osm_id: $dst}) CALL algo.AStar({sourceNode: a, targetNode: b, relTypes: ['ROAD'], weightProp: 'travel_s', latitudeProperty: 'lat', longitudeProperty: 'lon'}) YIELD path, pathWeight RETURN pathWeight, length(path) AS hops;
