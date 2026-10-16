"""Intake tests. No Bedrock calls: llm.converse is monkeypatched with canned tool responses."""
import pytest

from graphdispatch import db, llm
from graphdispatch.intake import IntakeRejected, take_call
from graphdispatch.ops import address_id, recall, why

LAT, LON = 37.3360, -121.8900
TYPES = {"burn", "cardiac_arrest", "hazmat_spill", "major_trauma", "pediatric_trauma", "stroke", "structure_fire"}


def canned(incident_type, hazards=(), address_label=None, tool_name="classify_call"):
    def fake(system, messages, tools=None, max_tokens=300, force_tool=None, model_id=None):
        assert force_tool == "classify_call" and tools[0]["name"] == "classify_call"
        props = tools[0]["input_schema"]["properties"]
        assert set(props["incident_type"]["enum"]) == TYPES                      # enum comes from the graph
        assert set(props["hazards"]["items"]["enum"]) == {"oxygen_storage", "aggressive_dog"}
        return {"tool_name": tool_name, "text": "", "stop_reason": "tool_use", "input_tokens": 1, "output_tokens": 1,
                "latency_ms": 1.0,
                "tool_input": {"incident_type": incident_type, "hazards": list(hazards), "address_label": address_label,
                               "confidence": 0.95, "reason": "canned"}}
    return fake


def runtime_counts():
    return {r[0]: r[1] for r in db.read("runtime_label_counts")}


def test_address_normalization():
    assert address_id("200 Demo Street") == address_id("200 demo st.") == address_id(" 200  DEMO St ") == "200 demo st"
    assert address_id("5 Main Boulevard") == "5 main blvd"
    assert address_id("device@37.3360,-121.8900") == "device@37.3360,-121.8900"


def test_i1_caller_reported_hazard_counts_in_the_same_call(monkeypatch):
    monkeypatch.setattr(llm, "converse", canned("structure_fire", ["oxygen_storage"]))
    r = take_call("caller-201", "smoke, neighbor uses oxygen", LAT, LON, address_override="200 Demo Street")
    units = {u["unit_id"]: u for u in r["recommendation"]["units"]}
    assert "HM26" in units and "oxygen_storage" in units["HM26"]["reason"]
    assert "UNMET" not in r["explanation"] and "added by oxygen_storage" in r["explanation"]
    haz = recall(r["incident_id"])["hazards"]
    assert [h["reported_by"] for h in haz] == ["caller"]
    assert "confidence" not in r["explanation"].lower()
    assert why(r["decision_id"])["incident"]["status"] == "open"   # never dispatched


def test_i2_second_call_recalls_hazard_and_first_incident(monkeypatch):
    monkeypatch.setattr(llm, "converse", canned("structure_fire", ["oxygen_storage"]))
    first = take_call("caller-201", "fire", LAT, LON, address_override="200 Demo Street")
    monkeypatch.setattr(llm, "converse", canned("cardiac_arrest"))
    second = take_call("caller-202", "he collapsed", LAT, LON, address_override="200 Demo St")
    w = why(second["decision_id"])
    assert [i["incident_id"] for i in w["recalled_incidents"]] == [first["incident_id"]]
    assert len(w["recalled_hazards"]) == 1 and w["recalled_hazards"][0]["kind"] == "oxygen_storage"
    assert "Crew note: Stored oxygen accelerates fire; no open flame" in second["explanation"]


@pytest.mark.parametrize("fake", [canned("alien_attack"), canned("stroke", ["unicorns"]),
                                  canned("stroke", tool_name="something_else")])
def test_i3_invalid_model_output_rejected_and_nothing_written(monkeypatch, fake):
    monkeypatch.setattr(llm, "converse", fake)
    with pytest.raises(IntakeRejected):
        take_call("caller-x", "text", LAT, LON)
    assert runtime_counts() == {}


def test_i4_no_address_gives_device_label(monkeypatch):
    monkeypatch.setattr(llm, "converse", canned("cardiac_arrest"))
    r = take_call("caller-203", "he collapsed", LAT, LON)
    assert why(r["decision_id"])["incident"]["address"] == "device@37.3360,-121.8900"
    assert r["classification"]["address_label_used"] == "device@37.3360,-121.8900"


def test_model_address_label_used_when_no_override(monkeypatch):
    monkeypatch.setattr(llm, "converse", canned("cardiac_arrest", address_label="200 Demo Street"))
    r = take_call("caller-204", "he collapsed at 200 Demo Street", LAT, LON)
    assert why(r["decision_id"])["incident"]["address"] == "200 Demo Street"


def test_call_text_and_model_stored(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")
    monkeypatch.setattr(llm, "converse", canned("cardiac_arrest"))
    r = take_call("caller-205", "synthetic words", LAT, LON)
    row = db.graph().ro_query("MATCH (i:Incident {incident_id: $id}) RETURN i.call_text, i.intake_model, i.synthetic",
                              {"id": r["incident_id"]}).result_set[0]
    assert row == ["synthetic words", "test-model", True]
