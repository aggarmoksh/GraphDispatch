"""QUERIES.md must match queries.cypher; README links, images, section order and key numbers must hold up."""
import json
import re
from pathlib import Path

from graphdispatch import db

ROOT = Path(__file__).resolve().parent.parent


def test_queries_md_is_in_sync_with_queries_cypher():
    md = (ROOT / "QUERIES.md").read_text(encoding="utf-8")
    sections = dict(re.findall(r"### `(\w+)`\n.*?```cypher\n(.*?)\n```", md, re.S))
    q = db.queries()
    assert set(sections) == set(q), (sorted(set(q) - set(sections)), sorted(set(sections) - set(q)))
    for name, text in q.items():
        assert sections[name] == text, f"Cypher for {name} differs between QUERIES.md and queries.cypher (rerun scripts/gen_queries_md.py)"
    assert "GRAPH.EXPLAIN" in md and "PROFILE effective_requirements" in md and "EXPLAIN unit_candidates" in md
    purposes = dict(re.findall(r"-- \[(\w+)\] ([^\n]*)", (ROOT / "graphdispatch" / "queries.cypher").read_text(encoding="utf-8")))
    for name, why in purposes.items():
        assert f"- Purpose: {why.strip()}" in md, name


def link_targets(text):
    out = re.findall(r"\]\(([^)\s]+)\)", text)
    return [t for t in out if not t.startswith(("http://", "https://", "#", "mailto:"))]


def test_readme_local_links_and_images_resolve():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    targets = link_targets(readme)
    assert len(targets) >= 12
    for t in targets:
        assert (ROOT / t.split("#")[0]).exists(), t
    for img in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme):
        assert (ROOT / img).stat().st_size > 10_000, img


def test_readme_sections_in_the_required_order():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    heads = re.findall(r"^## (.+)$", readme, re.M)
    want = ["What the graph decides", "Live demo", "Why a graph", "Graph model", "Cypher queries", "Architecture", "Setup", "Deployment",
            "Data sources and licenses", "Limitations", "AI assistance", "Friction log", "Hackathon tracks entered", "Next", "License"]
    assert heads == want, heads
    assert readme.count("```mermaid") == 2
    assert "http://3.220.38.68" in readme and "synthetic data, plain http" in readme.lower()


def test_readme_numbers_match_their_source_files():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    results = (ROOT / "eval" / "RESULTS.md").read_text(encoding="utf-8")
    for cell in ("38.1 / 48.3", "0.0 / 0.1", "1274.3 / 1585.0"):
        assert cell in readme and cell in results, cell
    m = re.search(r"\| A GraphDispatch \| 0 \| 0\.0 \| 0 \|", results)
    assert m and "| 0 | 195 | 2190 |" in readme
    counts = json.loads((ROOT / "docs" / "seed_counts.json").read_text(encoding="utf-8"))
    assert f"{counts['nodes_total']:,} nodes and {counts['relationships_total']:,} relationships" in readme
    for label, n in counts["nodes"].items():
        assert re.search(rf"\| {label} \| {n:,} \|", readme), label
    for rel, n in counts["relationships"].items():
        assert re.search(rf"\| {rel} \| {n:,} \|", readme), rel
    assert f"{len(db.queries())} named" in readme


def test_license_is_mit_with_the_placeholder_still_to_fill():
    lic = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert lic.startswith("MIT License") and "[COPYRIGHT HOLDER]" in lic
