import asyncio
import os

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier

auth = JWTVerifier(
    public_key=os.getenv("JWT_SECRET"),
    algorithm="HS256",
)

mcp = FastMCP(
    name="Medical Wizard MCP",
    version=os.getenv("MCP_VERSION", "local"),
    auth=auth,
)


if __name__ == "__main__":
    asyncio.run(mcp.run_http_async(
        host=os.getenv("FASTMCP_HOST", "0.0.0.0"),
        port=int(os.getenv("FASTMCP_PORT", "8000")),
        stateless_http=True,
        json_response=True,
    ))
