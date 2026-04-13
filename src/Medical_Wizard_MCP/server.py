import time
from typing import Any

from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from .tools._responses import conversation_id_var, request_start_var


class AuditContextMiddleware(Middleware):
    async def on_call_tool(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        headers = get_http_headers(include_all=True)
        conversation_token = conversation_id_var.set(
            headers.get("x-conversation-id") or headers.get("conversation-id")
        )
        request_token = request_start_var.set(time.perf_counter())
        try:
            return await call_next(context)
        finally:
            conversation_id_var.reset(conversation_token)
            request_start_var.reset(request_token)
