"""One error shape for the whole API: {"type", "title", "status", "detail"}."""

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def problem(status: int, detail: object = None) -> JSONResponse:
    title = HTTPStatus(status).phrase
    body = {"type": title.lower().replace(" ", "-"), "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(jsonable_encoder(body), status_code=status)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem(exc.status_code, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        return problem(422, exc.errors())
