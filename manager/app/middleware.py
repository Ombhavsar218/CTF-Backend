import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next: Callable):
        supplied_id = request.headers.get("X-Request-ID", "")
        try:
            request_id = str(uuid.UUID(supplied_id))
        except (ValueError, AttributeError, TypeError):
            request_id = str(uuid.uuid4())

        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
