"""The only module that talks to FalkorDB. Reads connection settings from .env."""
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from falkordb import FalkorDB

load_dotenv()
GRAPH_NAME = "sjfd"
_QUERIES = None
_GRAPH = None


def queries():
    global _QUERIES
    if _QUERIES is None:
        text = Path(__file__).with_name("queries.cypher").read_text(encoding="utf-8")
        _QUERIES = {m.group(1): m.group(2).strip()
                    for m in re.finditer(r"-- \[(\w+)\][^\n]*\n(.*?);[ \t]*(?:\n|$)", text, re.S)}
    return _QUERIES


def graph():
    global _GRAPH
    if _GRAPH is None:
        client = FalkorDB(
            host=os.getenv("FALKORDB_HOST", "localhost"),
            port=int(os.getenv("FALKORDB_PORT", "6379")),
            username=os.getenv("FALKORDB_USERNAME") or None,
            password=os.getenv("FALKORDB_PASSWORD") or None,
        )
        _GRAPH = client.select_graph(GRAPH_NAME)
    return _GRAPH


def run(name, params=None, timings=None):
    """Run a named query from queries.cypher; append (name, ms) to timings if given."""
    q = queries()[name]
    t0 = time.perf_counter()
    res = graph().query(q, params or {})
    if timings is not None:
        timings.append((name, (time.perf_counter() - t0) * 1000))
    return res.result_set
