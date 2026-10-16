import time

import pytest

from graphdispatch import db, ops
from graphdispatch.ops import UnknownHazardKind, add_hazard, run_call, why
from graphdispatch.recommend import hospital_label, recommend

LABEL, LAT, LON = "300 Test Way", 37.3360, -121.8900


def call(now, caller="caller-h"):
    return run_call(caller, LABEL, LAT, LON, "structure_fire", now=now)


def unit_ids(out):
    return {u["unit_id"] for u in out["recommendation"]["units"]}


def test_h1_no_hazard_no_hazmat():
    out = call(int(time.time()))
    assert "HM26" not in unit_ids(out)
    assert all(u["reason"] == "base" for u in out["recommendation"]["units"])


def test_h2_active_oxygen_hazard_adds_hazmat():
    now = int(time.time())
    first = call(now)
    add_hazard(LABEL, "oxygen_storage", "synthetic", now - 10, now + 30 * 86400, incident_id=first["incident_id"], now=now)
    second = call(now + 60, "caller-h2")
    units = {u["unit_id"]: u for u in second["recommendation"]["units"]}
    assert "HM26" in units and "oxygen_storage" in units["HM26"]["reason"]
    assert (unit_ids(second) - {"HM26"}) == unit_ids(first)
    w = why(second["decision_id"])
    chose = {u["unit_id"]: u for u in w["chose"]}
    assert "oxygen_storage" in chose["HM26"]["reason"] and chose["T8"]["reason"] == "base"
    assert w["recalled_hazards"] and "no open flame" in w["recalled_hazards"][0]["crew_note"]
    text = ops.explain_why(w)
    print(text)
    assert "added by oxygen_storage" in text and "Crew note: Stored oxygen accelerates fire; no open flame" in text


def test_h3_expired_hazard_adds_nothing():
    now = int(time.time())
    first = call(now)
    add_hazard(LABEL, "oxygen_storage", "synthetic", now - 1000, now - 10, incident_id=first["incident_id"], now=now)
    second = call(now + 60, "caller-h3")
    assert "HM26" not in unit_ids(second)


def test_h4_unavailable_hazmat_recorded_as_unmet():
    now = int(time.time())
    first = call(now)
    add_hazard(LABEL, "oxygen_storage", "synthetic", now - 10, now + 86400, incident_id=first["incident_id"], now=now)
    db.write("set_unit_status", {"unit_id": "HM26", "status": "assigned"})
    second = call(now + 60, "caller-h4")
    assert "HM26" not in unit_ids(second)
    assert unit_ids(second) == unit_ids(first)
    w = why(second["decision_id"])
    assert [m["capability"] for m in w["unmet"]] == ["hazmat"]
    text = ops.explain_why(w)
    print(text)
    assert "UNMET: hazmat (added by oxygen_storage)" in text


def test_h5_unknown_hazard_kind_refused():
    with pytest.raises(UnknownHazardKind) as e:
        add_hazard(LABEL, "unicorns", "synthetic", 0, 10)
    assert "oxygen_storage" in str(e.value) and "aggressive_dog" in str(e.value)
    assert db.read("count_labels") and not [r for r in db.read("runtime_label_counts") if r[0] == "Hazard"]


def test_h6_effective_requirements_is_one_query(monkeypatch):
    now = int(time.time())
    first = call(now)
    add_hazard(LABEL, "oxygen_storage", "synthetic", now - 10, now + 86400, incident_id=first["incident_id"], now=now)
    second_id = ops.create_incident("caller-h6", LABEL, LAT, LON, "structure_fire", now=now + 60)
    calls = []
    real = db.read

    def spy(name, params=None, timings=None):
        calls.append(name)
        return real(name, params, timings)

    monkeypatch.setattr(db, "read", spy)
    rec = recommend(LAT, LON, "structure_fire", incident_id=second_id, now=now + 60)
    assert calls.count("effective_requirements") == 1 and "required_caps" not in calls
    assert rec["requirements"]["hazmat"] == {"need": 1, "sources": [rec["requirements"]["hazmat"]["sources"][0]]}
    assert rec["requirements"]["hazmat"]["sources"][0].endswith(":oxygen_storage")
    assert rec["requirements"]["fire_suppression"]["sources"] == ["base"]


def test_hazard_kind_without_adds_changes_nothing():
    now = int(time.time())
    first = call(now)
    add_hazard(LABEL, "aggressive_dog", "synthetic", now - 10, now + 86400, incident_id=first["incident_id"], now=now)
    second = call(now + 60, "caller-dog")
    assert unit_ids(second) == unit_ids(first)
    assert "Animal on premises" in why(second["decision_id"])["recalled_hazards"][0]["crew_note"]


def test_trauma_levels_shown_without_changing_choice():
    rec = recommend(37.3300, -121.9300, "major_trauma")
    c = rec["hospital"]["chosen"]
    assert c["level"] in ("I", "II") and "level" in hospital_label(c)
    peds = recommend(37.3100, -121.8600, "pediatric_trauma")["hospital"]["chosen"]
    assert peds["name"] == "Santa Clara Valley Medical Center" and peds["level"] == "II"
    cardiac = recommend(37.3360, -121.8900, "cardiac_arrest")["hospital"]["chosen"]
    assert cardiac["level"] is None
