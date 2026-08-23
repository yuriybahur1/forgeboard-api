from uuid import uuid4

import pytest
import structlog
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
from prometheus_client import generate_latest
from starlette.requests import Request

from workstream.core.errors import AppError
from workstream.main import app
from workstream.observability import request_middleware

pytestmark = pytest.mark.unit


async def test_request_id_validation_logging_and_normalized_metrics(capsys) -> None:
    router = APIRouter()

    @router.get("/_test/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"id": item_id}

    app.include_router(router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        accepted = await client.get("/health/live", headers={"X-Request-ID": "valid.request-1"})
        replaced = await client.get("/health/live", headers={"X-Request-ID": "invalid request id"})
    assert accepted.headers["X-Request-ID"] == "valid.request-1"
    assert replaced.headers["X-Request-ID"] != "invalid request id"
    assert "valid.request-1" in capsys.readouterr().out

    raw_id = str(uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        await client.get(f"/_test/items/{raw_id}")
    metrics = generate_latest().decode()
    assert raw_id not in metrics
    assert "/_test/items/{item_id}" in metrics


async def test_expected_error_is_clean_and_unexpected_is_sanitized(capsys) -> None:
    router = APIRouter()

    @router.get("/_test/expected")
    async def expected() -> None:
        raise AppError(409, "expected", "expected")

    @router.get("/_test/unexpected")
    async def unexpected() -> None:
        raise RuntimeError("password=SuperSecret token=SecretToken")

    app.include_router(router)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://testserver"
    ) as client:
        expected_response = await client.get("/_test/expected")
        unexpected_response = await client.get("/_test/unexpected")
    assert expected_response.status_code == 409
    assert unexpected_response.status_code == 500
    body = unexpected_response.json()
    assert body["code"] == "internal_error" and body["request_id"]
    assert (
        "SuperSecret" not in unexpected_response.text
        and "SecretToken" not in unexpected_response.text
    )
    logs = capsys.readouterr().out
    assert logs.count("unhandled_request_exception") == 1


async def test_request_context_is_cleared_when_downstream_raises() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/failure",
            "raw_path": b"/failure",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
        }
    )

    async def fail(_: Request):
        raise RuntimeError("downstream failure")

    with pytest.raises(RuntimeError, match="downstream failure"):
        await request_middleware(request, fail)
    assert structlog.contextvars.get_contextvars() == {}
