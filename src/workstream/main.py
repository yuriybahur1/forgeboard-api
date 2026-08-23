import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response
from redis.asyncio import Redis
from sqlalchemy import text

from workstream.core.config import get_settings
from workstream.core.errors import AppError, app_error_handler, validation_error_handler
from workstream.db.session import async_engine
from workstream.modules.auth.router import router as auth_router
from workstream.modules.organizations.router import router as organization_router
from workstream.modules.work.router import router as work_router
from workstream.observability import configure_logging, metrics_response, request_middleware

settings = get_settings()
configure_logging(settings.log_json)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    yield
    await app.state.redis.aclose()
    await async_engine.dispose()


app = FastAPI(
    title="Workstream API", version="1.0.0", lifespan=lifespan, docs_url="/docs", redoc_url="/redoc"
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "If-Match"],
)
app.middleware("http")(request_middleware)
app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
app.include_router(auth_router, prefix="/api/v1")
app.include_router(organization_router, prefix="/api/v1")
app.include_router(work_router, prefix="/api/v1")


@app.get("/health/live", include_in_schema=False)
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def ready() -> dict[str, object]:
    states: dict[str, str] = {}
    try:
        async with asyncio.timeout(2), async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            states["postgres"] = "ok"
    except Exception:
        states["postgres"] = "unavailable"
    try:
        async with asyncio.timeout(2):
            states["redis"] = "ok" if await app.state.redis.ping() else "unavailable"
    except Exception:
        states["redis"] = "unavailable"
    if "unavailable" in states.values():
        raise AppError(503, "not_ready", "One or more critical dependencies are unavailable")
    return {"status": "ok", "dependencies": states}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return metrics_response()
