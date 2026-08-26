from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from attendance.services import auth

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


class NotAuthenticated(Exception):
    pass


async def require_login(request: Request) -> str:
    token = request.cookies.get(auth.SESSION_COOKIE_NAME)
    username = auth.read_session_token(token) if token else None
    if username is None:
        raise NotAuthenticated()
    return username
