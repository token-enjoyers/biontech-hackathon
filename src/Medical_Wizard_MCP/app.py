from ._mcp import mcp
from .server import AuditContextMiddleware

mcp.add_middleware(AuditContextMiddleware())
