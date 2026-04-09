import os

from fastmcp import FastMCP

from .server import AuditContextMiddleware

mcp = FastMCP(
    name="Medical Wizard MCP",
    version=os.getenv("MCP_VERSION", "local"),
    middleware=[AuditContextMiddleware()],
)
