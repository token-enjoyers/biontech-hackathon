import os

from fastmcp import FastMCP

mcp = FastMCP(
    name="Medical Wizard MCP",
    version=os.getenv("MCP_VERSION", "local"),
)
