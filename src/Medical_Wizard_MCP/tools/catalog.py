from __future__ import annotations

from typing import Any

from ..server import mcp
from ._responses import list_response
from ._tool_catalog import list_tool_metadata


@mcp.tool()
async def describe_tools(
    tool_names: list[str] | None = None,
    category: str | None = None,
    output_kind: str | None = None,
) -> dict[str, Any]:
    """Meta tool for LLM routing.

Use this first when you are unsure which MCP tool to call. It returns a structured catalog with each tool's category, output kind, canonical parameters, aliases, routing hints, and recommended next tools.

Avoid calling this when you already know the exact tool you need.
    """
    items = list_tool_metadata(
        tool_names=tool_names,
        category=category,
        output_kind=output_kind,
    )
    return list_response(
        tool_name="describe_tools",
        data_type="tool_catalog",
        items=items,
        quality_note="The catalog is generated from server-maintained metadata and is intended to help attached LLMs choose tools more reliably.",
        coverage="All MCP tools currently registered by this server.",
        queried_sources=["server_catalog"],
        evidence_sources=["server_catalog"],
        evidence_trace=[
            {
                "step": "load_server_tool_catalog",
                "sources": ["server_catalog"],
                "note": "Returns server-maintained metadata about available tools and routing hints.",
                "filters": {
                    "tool_names": tool_names or [],
                    "category": category,
                    "output_kind": output_kind,
                },
                "output_kind": "raw",
            }
        ],
        requested_filters={
            "tool_names": tool_names or [],
            "category": category,
            "output_kind": output_kind,
        },
    )
