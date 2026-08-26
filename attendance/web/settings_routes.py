from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request

from attendance.router_adapter import build_router_adapter
from attendance.services import settings_service
from attendance.web.deps import require_login, templates

router = APIRouter()


@router.get("/settings")
async def settings_form(request: Request, username: str = Depends(require_login)):
    settings = await settings_service.get_settings()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"username": username, "settings": settings, "test_result": None, "saved": False},
    )


@router.post("/settings")
async def settings_submit(
    request: Request,
    poll_interval_seconds: int = Form(...),
    absence_timeout_minutes: int = Form(...),
    long_absence_hint_hours: int = Form(...),
    router_adapter: str = Form(...),
    router_base_url: str = Form(...),
    router_username: str = Form(...),
    router_password: str = Form(""),
    timezone: str = Form(...),
    username: str = Depends(require_login),
):
    await settings_service.update_settings(
        poll_interval_seconds=poll_interval_seconds,
        absence_timeout_minutes=absence_timeout_minutes,
        long_absence_hint_hours=long_absence_hint_hours,
        router_adapter=router_adapter,
        router_base_url=router_base_url,
        router_username=router_username,
        router_password=router_password or None,
        timezone=timezone,
    )
    settings = await settings_service.get_settings()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"username": username, "settings": settings, "test_result": None, "saved": True},
    )


@router.post("/settings/test-connection")
async def settings_test_connection(
    request: Request,
    router_adapter: str = Form(...),
    router_base_url: str = Form(...),
    router_username: str = Form(...),
    router_password: str = Form(""),
    username: str = Depends(require_login),
):
    """Проверяет соединение с введёнными (ещё не обязательно сохранёнными)
    параметрами роутера — именно эта кнопка нужна на месте у роутера, чтобы
    быстро подобрать рабочие креды до сохранения настроек."""
    current = await settings_service.get_settings()
    password = router_password or current.router_password

    adapter = build_router_adapter(router_adapter, router_base_url, router_username, password)
    try:
        result = await adapter.get_connected_devices()
    finally:
        await adapter.close()

    if result.success:
        test_result = {
            "ok": True,
            "message": f"Успешно: устройств в сети — {len(result.devices)}",
            "devices": result.devices,
        }
    else:
        test_result = {"ok": False, "message": result.error, "devices": []}

    return templates.TemplateResponse(
        request,
        "settings.html",
        {"username": username, "settings": current, "test_result": test_result, "saved": False},
    )


@router.get("/logs")
async def logs(request: Request, username: str = Depends(require_login)):
    from attendance.database import repository as repo

    events = await repo.list_recent_events(limit=300)
    return templates.TemplateResponse(request, "logs.html", {"username": username, "events": events})
