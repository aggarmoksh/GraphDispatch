"""T6: pure stroke-rule tests with fake numbers (both branches and boundaries)."""
from graphdispatch.rules import stroke_bypass

CAP = {"name": "Cap", "eta_s": 500.0}
FB = {"name": "Fb", "eta_s": 100.0}


def test_t6_uses_capable_within_limits():
    chosen, text, used = stroke_bypass(CAP, FB, 1800, 2700)
    assert chosen is CAP and used
    assert "Cap +400 s over Fb, within 1800 s AHA bypass limit" in text


def test_t6_falls_back_when_extra_too_large():
    chosen, text, used = stroke_bypass({"name": "Cap", "eta_s": 2000.0}, FB, 1800, 2700)
    assert chosen is FB and not used
    assert "+1900 s over Fb exceeds 1800 s AHA bypass limit" in text


def test_t6_falls_back_when_total_too_large():
    chosen, text, used = stroke_bypass({"name": "Cap", "eta_s": 2800.0}, {"name": "Fb", "eta_s": 2500.0}, 1800, 2700)
    assert chosen["name"] == "Fb" and not used
    assert "total 2800 s exceeds 2700 s limit" in text


def test_t6_boundaries_inclusive():
    assert stroke_bypass({"name": "Cap", "eta_s": 1900.0}, FB, 1800, 2700)[2]
    assert not stroke_bypass({"name": "Cap", "eta_s": 1900.5}, FB, 1800, 2700)[2]
    assert stroke_bypass({"name": "Cap", "eta_s": 2700.0}, {"name": "Fb", "eta_s": 2600.0}, 1800, 2700)[2]


def test_t6_missing_hospitals():
    assert stroke_bypass(None, FB, 1800, 2700)[0] is FB
    assert stroke_bypass(CAP, None, 1800, 2700)[0] is CAP
    assert stroke_bypass(None, None, 1800, 2700)[0] is None
