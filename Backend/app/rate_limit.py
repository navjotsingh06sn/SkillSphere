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
        is_interview_code_run = (
            request.url.path.startswith("/api/interviews/")
            and request.url.path.endswith("/run")
        )
        if request.method == "POST" and is_interview_code_run:
            limit = (10, 60)
        if request.method != "POST" or limit is None:
            return await call_next(request)

        max_requests, window_seconds = limit
        now = monotonic()
        client_ip = request.client.host if request.client else "unknown"
        key_path = "interview_code_run" if is_interview_code_run else request.url.path
        key = (client_ip, key_path)
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

