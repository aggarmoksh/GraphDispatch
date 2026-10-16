"""Plain-language labels and the structured rule the page renders. No Bedrock calls."""
from fastapi.testclient import TestClient

from graphdispatch import api, db
from graphdispatch.rules import stroke_bypass

client = TestClient(api.app)
HOSP = "Regional Medical Center of San Jose"


def test_every_capability_and_incident_type_has_a_label():
    caps = {r[0] for r in db.graph().ro_query("MATCH (c:Capability) RETURN c.name").result_set}
    types = {r[0] for r in db.read("incident_type_names")}
    labels = api.labels()
    assert caps and types
    assert caps <= set(labels["capabilities"]), sorted(caps - set(labels["capabilities"]))
    assert types <= set(labels["incident_types"]), sorted(types - set(labels["incident_types"]))
    assert labels["capabilities"]["stroke_thrombectomy"] == "Clot removal (thrombectomy)"
    assert labels["capabilities"]["als"] == "Paramedic (ALS)"
    assert labels["incident_types"]["cardiac_arrest"] == "Cardiac arrest"
    assert all(v.strip() for d in labels.values() for v in d.values())


def test_meta_serves_labels():
    m = client.get("/api/meta").json()
    assert m["labels"]["capabilities"]["emergency"] == "Emergency department"
    assert m["labels"]["incident_types"]["hazmat_spill"] == "Hazmat spill"


def test_parse_rule_from_real_rules_py_output_both_branches():
    capable = {"name": HOSP, "eta_s": 551.0}
    fb = {"name": "O'Connor Hospital", "eta_s": 49.0}
    used = api.parse_rule(stroke_bypass(capable, fb, 1800, 2700)[1])
    assert used["kind"] == "bypass_used" and used["extra"] == 502 and used["max_extra"] == 1800
    assert used["capable"] == HOSP and used["fallback"] == "O'Connor Hospital" and used["total"] == 551
    assert used["source"] == "AHA Mission: Lifeline Stroke EMS algorithm"
    far = api.parse_rule(stroke_bypass({"name": HOSP, "eta_s": 2000.0}, fb, 1800, 2700)[1])
    assert far["kind"] == "bypass_declined_extra" and far["extra"] == 1951 and far["max_extra"] == 1800
    late = api.parse_rule(stroke_bypass({"name": HOSP, "eta_s": 2800.0}, {"name": "O'Connor Hospital", "eta_s": 2500.0}, 1800, 2700)[1])
    assert late["kind"] == "bypass_declined_total" and late["total"] == 2800 and late["max_total"] == 2700


def test_parse_rule_other_sentences():
    assert api.parse_rule("fastest hospital offering emergency: O'Connor Hospital (352 s)") == {
        "kind": "fastest", "capability": "emergency", "hospital": "O'Connor Hospital", "eta": 352}
    assert api.parse_rule("no destination hospital required for structure_fire")["kind"] == "no_destination"
    assert api.parse_rule("something new")["kind"] == "other"


def test_decision_payload_carries_structured_rule_for_s1():
    d = client.post("/api/recommend", json={"lat": 37.33, "lon": -121.93, "incident_type": "stroke"}).json()
    assert d["rule"]["kind"] == "bypass_used" and d["rule"]["extra"] == 502 and d["rule"]["max_extra"] == 1800
    assert d["skipped"][0]["name"] == "O'Connor Hospital" and "lacks stroke_thrombectomy" in d["skipped"][0]["reason"]
    assert d["rule_applied"].startswith(HOSP)  # the full sentence stays for the Why drawer
