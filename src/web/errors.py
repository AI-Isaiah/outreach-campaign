"""Standardized API error classes and global exception handler."""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class AppError(HTTPException):
    """Base application error with a machine-readable error_code."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        error_code: str = "UNKNOWN_ERROR",
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code


class NotFoundError(AppError):
    """Resource not found (404)."""

    def __init__(self, detail: str = "Resource not found") -> None:
        super().__init__(status_code=404, detail=detail, error_code="NOT_FOUND")


class ValidationError(AppError):
    """Request validation error (400)."""

    def __init__(self, detail: str = "Invalid request") -> None:
        super().__init__(status_code=400, detail=detail, error_code="VALIDATION_ERROR")


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """Global handler that converts AppError into a structured JSON response."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.error_code,
                "detail": exc.detail,
            }
        },
    )
