import asyncio
import time
import os

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .tools._responses import conversation_id_var, request_start_var

auth = JWTVerifier(
    public_key=os.getenv("JWT_SECRET"),
    algorithm="HS256",
)

mcp = FastMCP(
    name="Medical Wizard MCP",
    version=os.getenv("MCP_VERSION", "local"),
 #   auth=auth,
)


class AuditContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        conversation_id_var.set(request.headers.get("x-conversation-id"))
        request_start_var.set(time.perf_counter())
        return await call_next(request)


if __name__ == "__main__":
    asyncio.run(mcp.run_http_async(
        host=os.getenv("FASTMCP_HOST", "0.0.0.0"),
        port=int(os.getenv("FASTMCP_PORT", "8000")),
        stateless_http=True,
        json_response=True,
    ))
