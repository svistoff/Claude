"""Преобразование внутренних ошибок в понятные пользователю сообщения (§26 ТЗ)."""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


async def giveaway_error_handler(request: Request, exc: Exception) -> JSONResponse:
    status = 409 if "уже проведён" in str(exc) else 400
    return JSONResponse(status_code=status, content={"detail": str(exc)})


async def draw_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


async def source_adapter_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"detail": f"Не удалось получить комментарии.\n\nПричина: {exc}"},
    )


async def not_implemented_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=501, content={"detail": str(exc)})


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Необработанная ошибка при обработке %s", request.url)
    return JSONResponse(
        status_code=500,
        content={"detail": "Источник временно недоступен.\n\nПопробуйте повторить загрузку позже."},
    )
