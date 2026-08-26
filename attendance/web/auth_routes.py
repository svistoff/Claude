from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from attendance.database import repository as repo
from attendance.services import auth
from attendance.web.deps import templates

router = APIRouter()


@router.get("/login")
async def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    row = await repo.get_admin_by_username(username.strip())
    if row is None or not auth.verify_password(password, row["password_hash"]):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Неверный логин или пароль"}, status_code=401
        )
    response = RedirectResponse(url="/dashboard", status_code=303)
    token = auth.create_session_token(row["username"])
    response.set_cookie(
        auth.SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=None,
    )
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(auth.SESSION_COOKIE_NAME)
    return response
