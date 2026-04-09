import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .tools._responses import conversation_id_var, request_start_var


class AuditContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        conversation_id_var.set(request.headers.get("x-conversation-id"))
        request_start_var.set(time.perf_counter())
        return await call_next(request)
