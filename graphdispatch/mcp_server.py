"""Stdio MCP server exposing exactly the tools in graphdispatch/tools.py (official Python MCP SDK, `mcp` package).

Run: python -m graphdispatch.mcp_server   (graph chosen by env GRAPH_NAME, default sjfd)
Nothing but MCP protocol messages may go to stdout. There is no dispatch tool, no clear tool and no tool that
accepts Cypher; tool errors are returned as isError results, never raised through the transport.
"""
import json

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from .tools import ToolError, build_tools, run_tool

server_name = "graphdispatch"


async def on_list_tools(ctx, params):
    return types.ListToolsResult(tools=[types.Tool(name=t.name, description=t.description, input_schema=t.input_schema)
                                        for t in build_tools()])


async def on_call_tool(ctx, params):
    try:
        result = run_tool(params.name, params.arguments or {})
        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(result, default=str))])
    except ToolError as e:
        return types.CallToolResult(content=[types.TextContent(type="text", text=f"error: {e}")], is_error=True)
    except Exception as e:  # e.g. OutOfArea, database errors: report, never crash the server
        return types.CallToolResult(content=[types.TextContent(type="text", text=f"error: {type(e).__name__}: {e}")],
                                    is_error=True)


def make_server():
    return Server(server_name, on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def amain():
    server = make_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main():
    anyio.run(amain)


if __name__ == "__main__":
    main()
