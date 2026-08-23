from httpx import ASGITransport, AsyncClient

from workstream.main import app


async def test_liveness_and_request_id() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/health/live", headers={"X-Request-ID": "test-request-123"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-123"
    assert response.json() == {"status": "ok"}


async def test_validation_problem_details() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/api/v1/auth/register", json={})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
