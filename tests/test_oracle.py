"""Tests of the independent oracle (eval/oracle.py) on numbers the advisor confirmed with pure-Python Dijkstra."""
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
import oracle  # noqa: E402


def sc(**kw):
    base = {"id": "T", "incident_type": "stroke", "lat": 37.3300, "lon": -121.9300, "hazards": [], "prior_incidents": [], "busy_units": []}
    base.update(kw)
    return base


def test_oracle_imports_only_stdlib_and_networkx_and_never_graphdispatch():
    for name in ("oracle.py", "prompt.py", "baselines.py"):
        path = ROOT / "eval" / name
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods.update(a.name.split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                mods.add(n.module.split(".")[0])
        assert "graphdispatch" not in mods, (name, mods)
        if name == "oracle.py":
            assert mods <= set(sys.stdlib_module_names) | {"networkx"}, mods


def test_s1_matches_the_advisor_numbers():
    r = oracle.solve(sc())
    units = {u["capability"]: u for u in r["units"]}
    assert {u["unit_id"] for u in r["units"]} == {"E7", "M7"}
    assert round(units["als"]["eta_s"]) == 132 and round(units["transport"]["eta_s"]) == 132
    assert units["als"]["unit_id"] == "E7" and units["transport"]["unit_id"] == "M7"
    assert round(r["hospital_etas"]["Regional Medical Center of San Jose"]) == 551
    assert round(r["hospital_etas"]["O'Connor Hospital"]) == 49
    assert round(r["hospital_etas"]["Santa Clara Valley Medical Center"]) == 140
    assert r["hospital"]["name"] == "Regional Medical Center of San Jose" and r["hospital_rule"] == "bypass_used"
    assert r["nearest_hospital"]["name"] == "O'Connor Hospital"
    assert not r["unmet"]


def test_demo_point_structure_fire_with_oxygen_hazard():
    r = oracle.solve(sc(incident_type="structure_fire", lat=37.336, lon=-121.89, hazards=["oxygen_storage"]))
    by_unit = {u["unit_id"]: u for u in r["units"]}
    assert round(by_unit["T1"]["eta_s"]) == 47 and by_unit["T1"]["capability"] == "ladder"
    assert round(by_unit["HM26"]["eta_s"]) == 429 and by_unit["HM26"]["capability"] == "hazmat"
    assert r["requirements"]["hazmat"] == {"need": 1, "sources": ["hazard:oxygen_storage"]}
    assert r["hospital"] is None and r["hospital_rule"] == "no_destination"


def test_demo_point_cardiac_arrest_hospital():
    r = oracle.solve(sc(incident_type="cardiac_arrest", lat=37.336, lon=-121.89, hazards=["oxygen_storage"]))
    assert r["hospital"]["name"] == "O'Connor Hospital" and round(r["hospital"]["eta_s"]) == 352
    assert "hazmat" not in r["requirements"]            # oxygen_storage adds nothing to a cardiac arrest


def test_hazards_count_once_per_kind_and_busy_units_are_skipped():
    twice = oracle.solve(sc(incident_type="structure_fire", lat=37.336, lon=-121.89, hazards=["oxygen_storage", "oxygen_storage"]))
    assert twice["requirements"]["hazmat"]["need"] == 1
    busy = oracle.solve(sc(incident_type="structure_fire", lat=37.336, lon=-121.89, hazards=["oxygen_storage"], busy_units=["HM26"]))
    assert "HM26" not in {u["unit_id"] for u in busy["units"]} and busy["unmet"] == [{"capability": "hazmat", "missing": 1}]


def test_stroke_bypass_declines_when_limits_would_be_exceeded():
    t = oracle.WORLD().types["stroke"]
    assert (t["fallback"], t["max_extra_s"], t["max_total_s"]) == ("stroke_primary", 1800, 2700)


def test_scenarios_file_matches_the_protocol():
    data = json.loads((ROOT / "eval" / "scenarios.json").read_text(encoding="utf-8"))
    ids = [s["id"] for s in data["scenarios"]]
    assert len(ids) == 24 and ids[:7] == ["S1", "S2", "S3", "S4", "S5", "O1", "O2"] and data["seed"] == 42
    random_types = [s["incident_type"] for s in data["scenarios"] if s["id"].startswith("R")]
    assert len(random_types) == 17 and set(random_types) == set(oracle.WORLD().types)
    busy = [s["id"] for s in data["scenarios"] if s["busy_units"]]
    assert len(busy) == 2 and "S5" in busy
    w = oracle.WORLD()
    for s in data["scenarios"]:
        if s["id"].startswith("R"):
            near = w.nearest(s["lat"], s["lon"], 2)
            assert near[0][0] <= 300 and near[1][0] - near[0][0] >= 1.0


def test_protocol_embeds_the_exact_prompt_template():
    proto = (ROOT / "eval" / "PROTOCOL.md").read_text(encoding="utf-8")
    block = proto.split("<!-- PROMPT-TEMPLATE-START -->\n```text\n", 1)[1].split("\n```\n<!-- PROMPT-TEMPLATE-END -->", 1)[0]
    assert block == (ROOT / "eval" / "prompt_template.txt").read_text(encoding="utf-8").rstrip("\n")
    for must in ("us.anthropic.claude-haiku-4-5-20251001-v1:0", "temperature 0", "26 calls", "random.Random(42)", "one attempt per scenario"):
        assert must in proto or must.replace("one", "One") in proto, must


def test_prompt_builds_for_every_scenario_and_hides_nothing_from_the_oracle_inputs():
    import prompt
    data = json.loads((ROOT / "eval" / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    for s in data:
        system, user = prompt.build(s)
        assert "dispatch_plan" in system and f"Type: {s['incident_type']}" in user and "{" not in user
    o2 = next(s for s in data if s["id"] == "O2")
    assert "- oxygen_storage" in prompt.build(o2)[1] and "- structure_fire, within the last 30 days" in prompt.build(o2)[1]
    s5 = next(s for s in data if s["id"] == "S5")
    assert "- E8: station 8, status busy" in prompt.build(s5)[1]
    props = prompt.tool()["input_schema"]["properties"]
    assert len(props["assignments"]["items"]["properties"]["unit_ids"]["items"]["enum"]) == 22 and "none" in props["hospital"]["enum"]
