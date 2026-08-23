import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, cast
from uuid import uuid4

import structlog
from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status_class"])
LATENCY = Histogram("http_request_duration_seconds", "HTTP latency", ["method", "route"])
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
SECRET_PATTERN = re.compile(r"(?i)(password|token|authorization|cookie)(\s*[=:]\s*)([^\s,;&]+)")


def redact_secrets(_: object, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    def redact(value: Any) -> Any:
        if isinstance(value, str):
            return SECRET_PATTERN.sub(r"\1\2[REDACTED]", value)
        if isinstance(value, dict):
            return {key: redact(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return type(value)(redact(item) for item in value)
        return value

    return cast(dict[str, Any], redact(event_dict))


def configure_logging(json: bool) -> None:
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        redact_secrets,
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer(),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
    )


async def request_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    candidate = request.headers.get("x-request-id", "")
    request_id = candidate if SAFE_REQUEST_ID.fullmatch(candidate) else str(uuid4())
    request.state.request_id = request_id
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    started = time.perf_counter()
    response = await call_next(request)
    route = getattr(request.scope.get("route"), "path", "unmatched")
    duration = time.perf_counter() - started
    REQUESTS.labels(request.method, route, f"{response.status_code // 100}xx").inc()
    LATENCY.labels(request.method, route).observe(duration)
    response.headers["X-Request-ID"] = request_id
    structlog.get_logger().info(
        "request_complete",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        route=route,
        status_code=response.status_code,
        duration_ms=round(duration * 1000, 2),
    )
    structlog.contextvars.clear_contextvars()
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
