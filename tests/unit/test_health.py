import pytest
from fastapi.responses import JSONResponse

from workstream import main

pytestmark = pytest.mark.unit


class Connection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, _: object) -> None:
        return None


class Engine:
    def connect(self) -> Connection:
        return Connection()


class RedisOK:
    async def ping(self) -> bool:
        return True


class RedisDown:
    async def ping(self) -> bool:
        raise ConnectionError


async def test_readiness_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "async_engine", Engine())
    main.app.state.redis = RedisOK()
    assert await main.ready() == {
        "status": "ok",
        "dependencies": {"postgres": "ok", "redis": "ok"},
    }


async def test_readiness_reports_dependency_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "async_engine", Engine())
    main.app.state.redis = RedisDown()
    response = await main.ready()
    assert isinstance(response, JSONResponse)
    assert response.status_code == 503
    assert b'"postgres":"ok"' in response.body
    assert b'"redis":"unavailable"' in response.body
