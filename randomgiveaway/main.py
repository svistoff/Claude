"""FastAPI-приложение. Точка входа: uvicorn randomgiveaway.main:app"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from randomgiveaway.adapters.base import SourceAdapterError
from randomgiveaway.api.errors import (
    draw_error_handler,
    giveaway_error_handler,
    not_implemented_handler,
    source_adapter_error_handler,
    unhandled_error_handler,
)
from randomgiveaway.api.routes import router
from randomgiveaway.config import config
from randomgiveaway.database.database import close_db, init_db
from randomgiveaway.services.giveaways import GiveawayError
from randomgiveaway.services.random_engine import DrawError

logging.basicConfig(level=config.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(title="Random.ЕКБ ГИД API", lifespan=lifespan)
app.include_router(router)

app.add_exception_handler(GiveawayError, giveaway_error_handler)
app.add_exception_handler(DrawError, draw_error_handler)
app.add_exception_handler(SourceAdapterError, source_adapter_error_handler)
app.add_exception_handler(NotImplementedError, not_implemented_handler)
app.add_exception_handler(Exception, unhandled_error_handler)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
