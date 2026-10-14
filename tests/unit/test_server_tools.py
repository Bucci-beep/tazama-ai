import asyncio

from tazama.mcp.server import mcp


def test_server_exposes_expected_tools():
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert {
        "validate_observations",
        "calculate_sats",
        "compare_with_history",
    } <= names
