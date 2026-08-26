from __future__ import annotations

import os
import tempfile

import pytest_asyncio

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

from attendance.database.database import close_db, init_db  # noqa: E402
from attendance import config as config_module  # noqa: E402


@pytest_asyncio.fixture()
async def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)  # aiosqlite создаст файл заново
    original_path = config_module.config.db_path
    object.__setattr__(config_module.config, "db_path", path)
    try:
        conn = await init_db()
        yield conn
    finally:
        await close_db()
        object.__setattr__(config_module.config, "db_path", original_path)
        if os.path.exists(path):
            os.unlink(path)
