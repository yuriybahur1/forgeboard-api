from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(
        self, status: int, code: str, detail: str, *, headers: dict[str, str] | None = None
    ):
        self.status, self.code, self.detail, self.headers = status, code, detail, headers


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        {
            "type": f"https://workstream.local/problems/{exc.code}",
            "title": exc.code.replace("_", " ").title(),
            "status": exc.status,
            "detail": exc.detail,
            "instance": request.url.path,
            "code": exc.code,
            "request_id": getattr(request.state, "request_id", None),
        },
        status_code=exc.status,
        headers=exc.headers,
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors: list[dict[str, Any]] = [
        {"location": list(e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()
    ]
    return JSONResponse(
        {
            "type": "https://workstream.local/problems/validation_error",
            "title": "Validation Error",
            "status": 422,
            "detail": "Request validation failed",
            "instance": request.url.path,
            "code": "validation_error",
            "request_id": getattr(request.state, "request_id", None),
            "errors": errors,
        },
        status_code=422,
    )
