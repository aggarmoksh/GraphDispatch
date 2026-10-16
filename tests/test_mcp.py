"""M1: stdio MCP server tests through the official Python MCP client."""
import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from graphdispatch.tools import build_tools

EXPECTED = {"recommend_units", "recall_address", "explain_decision", "list_open_incidents", "unit_status", "report_hazard"}


async def _session_run(fn):
    env = dict(os.environ)
    env["GRAPH_NAME"] = "sjfd_test"
    params = StdioServerParameters(command=sys.executable, args=["-m", "graphdispatch.mcp_server"], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return await fn(s)


def test_m1_mcp_server_tools_and_errors():
    async def scenario(s):
        tools = (await s.list_tools()).tools
        ok = await s.call_tool("recommend_units", {"lat": 37.33, "lon": -121.93, "incident_type": "stroke"})
        bad = await s.call_tool("recommend_units", {"lat": 37.33, "lon": -121.93, "incident_type": "alien_attack"})
        ooa = await s.call_tool("recommend_units", {"lat": 37.45, "lon": -121.90, "incident_type": "stroke"})
        unknown = await s.call_tool("dispatch", {"decision_id": "x"})
        still_alive = await s.call_tool("unit_status", {})
        return tools, ok, bad, ooa, unknown, still_alive

    tools, ok, bad, ooa, unknown, alive = asyncio.run(_session_run(scenario))
    assert {t.name for t in tools} == EXPECTED and len(tools) == 6
    assert not any(w in t.name for t in tools for w in ("dispatch", "clear", "cypher", "query"))
    for t in tools:  # no tool accepts free query text: every string property is bounded or an enum
        for prop, spec in t.input_schema["properties"].items():
            assert prop not in ("cypher", "query", "statement"), (t.name, prop)
            if spec.get("type") == "string":
                assert "enum" in spec or "maxLength" in spec, (t.name, prop)
    assert not ok.is_error
    assert json.loads(ok.content[0].text)["hospital"]["chosen"]["name"] == "Regional Medical Center of San Jose"
    assert bad.is_error and "alien_attack" in bad.content[0].text
    assert ooa.is_error and "OutOfArea" in ooa.content[0].text
    assert unknown.is_error
    assert not alive.is_error and len(json.loads(alive.content[0].text)) == 22


def test_only_report_hazard_writes():
    writers = [t.name for t in build_tools() if t.writes]
    assert writers == ["report_hazard"]
