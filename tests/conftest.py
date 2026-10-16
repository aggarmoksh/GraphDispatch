"""Tests run against GRAPH_NAME=sjfd_test, loaded fresh from seed/ at session start. Never sjfd."""
import os
import sys
from pathlib import Path

os.environ["GRAPH_NAME"] = "sjfd_test"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from graphdispatch import db  # noqa: E402

import load  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _fresh_graph():
    assert db.graph_name() == "sjfd_test"
    db.drop_graph()
    load.load()
    yield


@pytest.fixture(autouse=True)
def _reset_runtime():
    """Each test starts with no runtime nodes and seed unit statuses."""
    assert db.graph_name() == "sjfd_test"
    db.write("wipe_runtime")
    load.reset_units()
    yield
