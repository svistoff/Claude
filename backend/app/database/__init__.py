"""Слой БД: engine, сессии, инициализация."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import BACKEND_DIR, get_settings
from .models import Base

_engine = None
_SessionLocal: sessionmaker | None = None


def _make_url() -> str:
    url = get_settings().database_url
    # Для sqlite с относительным путём — создаём директорию.
    if url.startswith("sqlite:///"):
        rel = url[len("sqlite:///"):]
        path = Path(rel)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path}"
    return url


def init_db() -> None:
    global _engine, _SessionLocal
    connect_args = {"check_same_thread": False} if "sqlite" in _make_url() else {}
    _engine = create_engine(_make_url(), connect_args=connect_args, future=True)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(_engine)


def get_session() -> Session:
    if _SessionLocal is None:
        init_db()
    assert _SessionLocal is not None
    return _SessionLocal()
