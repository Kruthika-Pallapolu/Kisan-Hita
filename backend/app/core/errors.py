from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging

logger = logging.getLogger("kisan_hita.api")


async def http_error_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": "http_error", "message": detail}})


async def validation_error_handler(request: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(part) for part in item["loc"] if part != "body"), "message": item["msg"]} for item in exc.errors()]
    return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "Please check the information and try again.", "details": errors}})


async def internal_error_handler(request: Request, exc: Exception):
    logger.error("Unhandled API error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "Something went wrong. Please try again."}})
