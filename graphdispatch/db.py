"""The only module that talks to FalkorDB. Reads connection settings from .env."""
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from falkordb import FalkorDB

load_dotenv()
_QUERIES = None
_CLIENT = None
_GRAPHS = {}


def graph_name():
    return os.getenv("GRAPH_NAME", "sjfd")


def queries():
    global _QUERIES
    if _QUERIES is None:
        text = Path(__file__).with_name("queries.cypher").read_text(encoding="utf-8")
        _QUERIES = {m.group(1): m.group(2).strip()
                    for m in re.finditer(r"-- \[(\w+)\][^\n]*\n(.*?);[ \t]*(?:\n|$)", text, re.S)}
    return _QUERIES


def client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = FalkorDB(
            host=os.getenv("FALKORDB_HOST", "localhost"),
            port=int(os.getenv("FALKORDB_PORT", "6379")),
            username=os.getenv("FALKORDB_USERNAME") or None,
            password=os.getenv("FALKORDB_PASSWORD") or None,
        )
    return _CLIENT


def graph():
    name = graph_name()
    if name not in _GRAPHS:
        _GRAPHS[name] = client().select_graph(name)
    return _GRAPHS[name]


def read(name, params=None, timings=None):
    """Read-only named query (GRAPH.RO_QUERY); append (name, ms) to timings if given."""
    t0 = time.perf_counter()
    res = graph().ro_query(queries()[name], params or {})
    if timings is not None:
        timings.append((name, (time.perf_counter() - t0) * 1000))
    return res.result_set


def write(name, params=None, timings=None):
    """Named query that may write (GRAPH.QUERY)."""
    t0 = time.perf_counter()
    res = graph().query(queries()[name], params or {})
    if timings is not None:
        timings.append((name, (time.perf_counter() - t0) * 1000))
    return res.result_set


def drop_graph():
    """Delete the current graph. Only allowed for graphs whose name ends with _test or _clonecheck."""
    name = graph_name()
    if not name.endswith(("_test", "_clonecheck")):
        raise RuntimeError(f"refusing to drop graph {name!r}")
    if name in client().list_graphs():
        graph().delete()
    _GRAPHS.pop(name, None)
