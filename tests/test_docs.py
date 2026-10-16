from pathlib import Path

from graphdispatch import db

ROOT = Path(__file__).resolve().parent.parent


def test_every_query_listed_in_agent_md():
    text = (ROOT / "AGENT.md").read_text(encoding="utf-8")
    missing = [n for n in db.queries() if f"`{n}`" not in text]
    assert not missing, f"queries missing from AGENT.md QUERIES section: {missing}"
