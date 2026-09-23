"""Общие зависимости и хелперы веб-слоя."""
from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import User


async def current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> User | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    return await session.get(User, uid)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def render(request: Request, name: str, user: User | None = None, **ctx) -> HTMLResponse:
    templates = request.app.state.templates
    settings = request.app.state.settings
    return templates.TemplateResponse(request, name, {"user": user, "settings": settings, **ctx})


def is_admin(user: User | None) -> bool:
    return user is not None and user.role == "Admin"


def position_class(pos: int | None) -> str:
    """CSS-класс ячейки по позиции: чем выше позиция, тем насыщеннее зелёный."""
    if pos is None:
        return "bmiss"
    if pos <= 3:
        return "b3"
    if pos <= 10:
        return "b10"
    if pos <= 20:
        return "b20"
    if pos <= 50:
        return "b50"
    return "bmiss"
