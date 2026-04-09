from typing import Any

from ..server import mcp
from ..version import get_mcp_version as resolve_mcp_version
from ..version import get_mcp_version_source
from ._responses import detail_response


@mcp.tool()
async def get_mcp_version() -> dict[str, Any]:
    """Return the currently running MCP version.

    The version is resolved from `MCP_VERSION` first, then `TAG_NAME`, and falls back to `local`.
    Use this to identify which deployed build is serving requests.
    """
    return detail_response(
        tool_name="get_mcp_version",
        data_type="server_version",
        item={
            "name": "Medical Wizard MCP",
            "version": resolve_mcp_version(),
            "version_source": get_mcp_version_source(),
        },
        quality_note="Server version is resolved from deployment environment variables and falls back to a local default.",
        coverage="Applies to the currently running MCP server instance.",
    )
