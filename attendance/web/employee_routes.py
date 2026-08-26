from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from attendance.database import repository as repo
from attendance.router_adapter import build_router_adapter
from attendance.services import settings_service, tz as tz_service
from attendance.services.status import compute_status
from attendance.web.deps import require_login, templates

router = APIRouter()


@router.get("/employees")
async def employees_list(request: Request, username: str = Depends(require_login)):
    employees = await repo.list_employees(include_inactive=True)
    devices = {}
    for e in employees:
        devices[e.id] = await repo.get_device_by_employee(e.id)
    return templates.TemplateResponse(
        request,
        "employees_list.html",
        {"employees": employees, "devices": devices, "username": username},
    )


@router.get("/employees/new")
async def employee_new_form(request: Request, username: str = Depends(require_login)):
    return templates.TemplateResponse(request, "employee_new.html", {"username": username})


@router.post("/employees/new")
async def employee_new_submit(
    request: Request, name: str = Form(...), username: str = Depends(require_login)
):
    employee_id = await repo.create_employee(name.strip())
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=303)


@router.get("/employees/{employee_id}")
async def employee_card(request: Request, employee_id: int, username: str = Depends(require_login)):
    employee = await repo.get_employee(employee_id)
    if employee is None:
        return RedirectResponse(url="/employees", status_code=303)

    settings = await settings_service.get_settings()
    tz_name = settings.timezone

    device = await repo.get_device_by_employee(employee_id)
    latest = await repo.get_latest_session(employee_id)
    status = compute_status(employee, device, latest)

    sessions = await repo.list_sessions_for_employee(employee_id, limit=30)
    history_rows = []
    for s in sessions:
        started = tz_service.parse_utc(s.started_at)
        ended = tz_service.parse_utc(s.ended_at) if s.ended_at else None
        duration = tz_service.format_duration((ended - started).total_seconds()) if ended else "—"
        history_rows.append(
            {
                "date": tz_service.format_local_date(s.started_at, tz_name),
                "started": tz_service.format_local_time(s.started_at, tz_name),
                "ended": tz_service.format_local_time(s.ended_at, tz_name) if s.ended_at else "—",
                "duration": duration,
            }
        )

    return templates.TemplateResponse(
        request,
        "employee_card.html",
        {
            "username": username,
            "employee": employee,
            "device": device,
            "status": status,
            "history_rows": history_rows,
            "tz_name": tz_name,
            "fmt_time": lambda v: tz_service.format_local_time(v, tz_name),
        },
    )


@router.post("/employees/{employee_id}/rename")
async def employee_rename(
    employee_id: int, name: str = Form(...), username: str = Depends(require_login)
):
    await repo.rename_employee(employee_id, name.strip())
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=303)


@router.post("/employees/{employee_id}/toggle-active")
async def employee_toggle_active(employee_id: int, username: str = Depends(require_login)):
    employee = await repo.get_employee(employee_id)
    if employee is not None:
        await repo.set_employee_active(employee_id, not employee.is_active)
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=303)


@router.get("/employees/{employee_id}/device")
async def employee_device_form(
    request: Request,
    employee_id: int,
    discover: bool = False,
    prefill_mac: str = "",
    username: str = Depends(require_login),
):
    employee = await repo.get_employee(employee_id)
    device = await repo.get_device_by_employee(employee_id)

    discovered = []
    discover_error = None
    if discover:
        settings = await settings_service.get_settings()
        adapter = build_router_adapter(
            settings.router_adapter,
            settings.router_base_url,
            settings.router_username,
            settings.router_password,
        )
        try:
            result = await adapter.get_connected_devices()
        finally:
            await adapter.close()
        if result.success:
            discovered = result.devices
        else:
            discover_error = result.error

    return templates.TemplateResponse(
        request,
        "employee_device.html",
        {
            "username": username,
            "employee": employee,
            "device": device,
            "discovered": discovered,
            "discover_error": discover_error,
            "prefill_mac": prefill_mac,
        },
    )


@router.post("/employees/{employee_id}/device")
async def employee_device_submit(
    employee_id: int,
    device_identifier: str = Form(...),
    device_name: str = Form(...),
    username: str = Depends(require_login),
):
    identifier = device_identifier.strip().upper()
    existing = await repo.get_device_by_identifier(identifier)
    if existing is not None and existing.employee_id != employee_id:
        # Устройство уже привязано к другому сотруднику — не позволяем дубликат.
        return RedirectResponse(
            url=f"/employees/{employee_id}/device?discover=0&error=duplicate", status_code=303
        )
    await repo.upsert_device(employee_id, identifier, device_name.strip())
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=303)
