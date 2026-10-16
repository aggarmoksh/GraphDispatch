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
    want = ["What the graph decides", "Live demo", "Why a graph", "Road closures (demonstration)", "Graph model", "Cypher queries", "Architecture",
            "Use the graph tools from Claude Desktop", "Setup", "Deployment", "Data sources and licenses", "Limitations", "AI assistance",
            "Friction log", "Hackathon tracks entered", "Next", "License"]
    assert heads == want, heads
    assert readme.count("```mermaid") == 2
    assert "https://d445nmo1mzx5s.cloudfront.net" in readme and "synthetic data" in readme.lower()
    assert "http://" + "3.220" not in readme                  # the bare-IP link is not presented
    assert "Demo video: [VIDEO LINK]" in readme or "Demo video:" in readme


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


def test_no_copyright_holder_placeholder_remains_anywhere_in_the_repo():
    import subprocess
    needle = "[COPYRIGHT" + " HOLDER]"                       # built in two parts so this file does not match itself
    standin = "<YOUR FULL" + " NAME>"
    files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True,
                           text=True, check=True).stdout.split()
    hits = [f for f in files if (ROOT / f).is_file()
            and any(x in (ROOT / f).read_text(encoding="utf-8", errors="ignore") for x in (needle, standin))]
    assert not hits, f"license holder placeholder still present in: {hits}"
    lic = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert lic.startswith("MIT License") and "Copyright (c) 2026 " in lic


def test_old_bare_ip_address_appears_in_no_tracked_file():
    import subprocess
    needle = "3.220" + ".38.68"                                   # built in two parts so this file does not match itself
    files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True,
                           text=True, check=True).stdout.split()
    hits = [f for f in files if (ROOT / f).is_file() and needle in (ROOT / f).read_text(encoding="utf-8", errors="ignore")]
    assert not hits, hits


def test_readme_track_01_text_and_ai_disclosure_wording():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert ("An LLM intake step turns the caller's words into one forced tool call whose values must come from the graph's own lists. "
            "The same graph operations are exposed as six typed MCP tools (five read-only, one that records a hazard); an MCP client such as "
            "Claude Desktop chooses among them. Dispatch stays a human action, and no tool accepts Cypher.") in readme
    assert "There is no free-form agent loop" not in readme
    assert "Road closures (demonstration)" in readme and "not part of the pre-registered evaluation" in readme
    disclosure = (ROOT / "AI_DISCLOSURE.md").read_text(encoding="utf-8")
    must = ("The author set the goal and scope, approved every phase before it ran, ran the field checks on the real product, did all AWS setup and deployment, "
            "and decided what was published. Claude (chat) acted as an advisor: it drafted the phase briefs, the research and the evaluation design, and independently "
            "re-checked results against the data. Claude Code wrote the code, tests and docs from those briefs. Amazon Bedrock (Claude Haiku 4.5) classifies caller text at runtime.")
    assert must in disclosure
    assert "The author set the goal and scope, approved every phase before it ran, ran the field checks on the real product, did all AWS setup and deployment, and decided what was published." in readme
