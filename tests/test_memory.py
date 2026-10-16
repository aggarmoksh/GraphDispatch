import time

from graphdispatch import db, ops
from graphdispatch.ops import add_hazard, recall, run_call, why

LABEL = "100 Example Ave"
LAT, LON = 37.3360, -121.8900


def test_t1_repeat_address_recalls_hazard_and_prior_incident():
    now = int(time.time())
    first = run_call("caller-001", LABEL, LAT, LON, "cardiac_arrest", now=now)
    hz = add_hazard(LABEL, "oxygen_storage", "synthetic: oxygen cylinders in garage", now, now + 30 * 86400,
                    incident_id=first["incident_id"], now=now)
    second = run_call("caller-002", "  100   EXAMPLE ave ", LAT, LON, "structure_fire", now=now + 60)
    rec = second["recalled"]
    print("T1 recall:", rec)
    assert [h["hazard_id"] for h in rec["hazards"]] == [hz]
    assert rec["hazards"][0]["kind"] == "oxygen_storage"
    assert [i["incident_id"] for i in rec["incidents"]] == [first["incident_id"]]
    w = why(second["decision_id"])
    assert [h["hazard_id"] for h in w["recalled_hazards"]] == [hz]
    assert [i["incident_id"] for i in w["recalled_incidents"]] == [first["incident_id"]]
    # first decision had nothing to recall
    assert why(first["decision_id"])["recalled_hazards"] == []
    assert recall(second["incident_id"], now + 60) == rec


def test_t2_expired_hazard_not_recalled():
    now = int(time.time())
    first = run_call("caller-001", LABEL, LAT, LON, "cardiac_arrest", now=now)
    add_hazard(LABEL, "aggressive_dog", "synthetic", now - 1000, now - 10, incident_id=first["incident_id"], now=now)
    second = run_call("caller-002", LABEL, LAT, LON, "structure_fire", now=now + 60)
    assert second["recalled"]["hazards"] == []
    assert len(second["recalled"]["incidents"]) == 1
    assert why(second["decision_id"])["recalled_hazards"] == []


def test_prior_incident_older_than_30_days_not_recalled():
    now = int(time.time())
    first = run_call("caller-001", LABEL, LAT, LON, "cardiac_arrest", now=now - 31 * 86400)
    second = run_call("caller-002", LABEL, LAT, LON, "structure_fire", now=now)
    assert second["recalled"]["incidents"] == []
    assert first["incident_id"] != second["incident_id"]
    assert db.graph_name() == "sjfd_test"
