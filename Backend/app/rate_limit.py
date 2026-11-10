from collections import defaultdict, deque
from time import monotonic

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class SensitiveRouteRateLimit(BaseHTTPMiddleware):
    """Small per-process sliding-window limit for sensitive development endpoints."""

    def __init__(self, app):
        super().__init__(app)
        self.requests = defaultdict(deque)
        self.limits = {
            "/api/auth/login": (10, 60),
            "/api/auth/account": (10, 60),
            "/api/auth/register": (5, 60),
            "/api/auth/forgot-password": (5, 60),
            "/api/auth/reset-password": (10, 60),
            "/api/resumes/upload": (10, 60),
        }

    async def dispatch(self, request: Request, call_next):
        limit = self.limits.get(request.url.path)
        if request.method != "POST" or limit is None:
            return await call_next(request)

        max_requests, window_seconds = limit
        now = monotonic()
        client_ip = request.client.host if request.client else "unknown"
        key = (client_ip, request.url.path)
        timestamps = self.requests[key]
        while timestamps and now - timestamps[0] >= window_seconds:
            timestamps.popleft()

        if len(timestamps) >= max_requests:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please wait before trying again."},
                headers={"Retry-After": str(window_seconds)},
            )

        timestamps.append(now)
        return await call_next(request)

