"""Роуты аутентификации: /api/login, /api/logout, /api/me."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, Request, Response
from pydantic import BaseModel

from .. import auth
from ..config import get_settings

router = APIRouter(prefix="/api", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict:
    auth.check_login_rate(request)
    settings = get_settings()
    ok = (body.username == settings.admin_user) and auth.verify_password(body.password)
    if not ok:
        # Единый ответ, чтобы не различать «нет пользователя» / «неверный пароль».
        response.status_code = 401
        return {"ok": False, "error": "Неверный логин или пароль."}
    csrf = auth.issue_session(response, body.username)
    return {"ok": True, "user": body.username, "csrf": csrf}


@router.post("/logout")
def logout(response: Response, user: str = Depends(auth.require_user)) -> dict:
    auth.clear_session(response)
    return {"ok": True}


@router.get("/me")
def me(session: str | None = Cookie(default=None, alias=auth.COOKIE_NAME)) -> dict:
    csrf = auth.get_csrf(session)
    if csrf is None:
        return {"authenticated": False}
    return {"authenticated": True, "user": get_settings().admin_user, "csrf": csrf}
