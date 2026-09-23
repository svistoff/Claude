"""Проекты: список, детальная страница-хаб, CRUD запросов/сайтов/профилей, запуск."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_session, get_sessionmaker
from ...domain.normalize import normalize_host
from ...domain.results import RunMode
from ...models import Profile, Project, Query, Site, User
from ...services.analytics import latest_positions
from ...services.runner import run_project_batch
from ..deps import current_user, is_admin, redirect, render

logger = logging.getLogger("posmon.web")
router = APIRouter()


async def _get_project(session: AsyncSession, project_id: int) -> Project | None:
    return await session.get(Project, project_id)


@router.get("/projects")
async def projects_list(
    request: Request,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if user is None:
        return redirect("/login")
    projects = (
        await session.execute(select(Project).order_by(Project.created_at.desc()))
    ).scalars().all()
    return render(request, "projects.html", user=user, projects=projects)


@router.post("/projects")
async def projects_create(
    request: Request,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    name: str = Form(...),
    depth: int = Form(50),
    description: str = Form(""),
):
    if user is None:
        return redirect("/login")
    if is_admin(user) and name.strip():
        session.add(Project(name=name.strip(), depth=depth, description=description.strip() or None))
        await session.commit()
    return redirect("/projects")


@router.post("/projects/{project_id}/edit")
async def projects_edit(
    project_id: int,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    name: str = Form(...),
    depth: int = Form(50),
    description: str = Form(""),
):
    if user is None:
        return redirect("/login")
    if is_admin(user):
        project = await _get_project(session, project_id)
        if project and name.strip():
            project.name = name.strip()
            project.depth = depth
            project.description = description.strip() or None
            await session.commit()
    return redirect(f"/projects/{project_id}")


@router.post("/projects/{project_id}/delete")
async def projects_delete(
    project_id: int,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if user is None:
        return redirect("/login")
    if is_admin(user):
        project = await _get_project(session, project_id)
        if project:
            await session.delete(project)  # каскадно удаляет запросы/сайты/профили/историю
            await session.commit()
    return redirect("/projects")


@router.post("/projects/{project_id}/toggle")
async def projects_toggle(
    project_id: int,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if user is None:
        return redirect("/login")
    if is_admin(user):
        project = await _get_project(session, project_id)
        if project:
            project.active = not project.active
            await session.commit()
    return redirect("/projects")


@router.get("/projects/{project_id}")
async def project_detail(
    project_id: int,
    request: Request,
    mode: str = RunMode.SEO.value,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if user is None:
        return redirect("/login")
    project = await _get_project(session, project_id)
    if project is None:
        return redirect("/projects")

    queries = (await session.execute(
        select(Query).where(Query.project_id == project_id).order_by(Query.query)
    )).scalars().all()
    sites = (await session.execute(
        select(Site).where(Site.project_id == project_id).order_by(Site.name)
    )).scalars().all()
    profiles = (await session.execute(
        select(Profile).where(Profile.project_id == project_id).order_by(Profile.name)
    )).scalars().all()

    latest = await latest_positions(session, project_id, mode)
    active_profiles = [p for p in profiles if p.active]

    # Таблица позиций: строки (запрос × сайт), колонки — профили.
    table_rows = []
    for q in queries:
        if not q.active:
            continue
        for s in sites:
            if not s.active:
                continue
            cells = []
            for p in active_profiles:
                row = latest.get((q.id, s.id, p.id))
                cells.append(row.position if row else None)
            table_rows.append({"query": q, "site": s, "cells": cells})

    return render(
        request, "project_detail.html", user=user, project=project,
        queries=queries, sites=sites, profiles=profiles,
        active_profiles=active_profiles, table_rows=table_rows, mode=mode,
    )


# ── Запросы ────────────────────────────────────────────────────────────────
@router.post("/projects/{project_id}/queries")
async def queries_add(
    project_id: int,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    queries_text: str = Form(...),
    group_name: str = Form(""),
    is_local: bool = Form(False),
):
    if user is None:
        return redirect("/login")
    if is_admin(user):
        for line in queries_text.splitlines():
            text = line.strip()
            if text:
                session.add(Query(
                    project_id=project_id, query=text,
                    group_name=group_name.strip() or None, is_local=is_local,
                ))
        await session.commit()
    return redirect(f"/projects/{project_id}")


@router.post("/queries/{query_id}/toggle")
async def query_toggle(
    query_id: int,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if user is None:
        return redirect("/login")
    q = await session.get(Query, query_id)
    if q and is_admin(user):
        q.active = not q.active
        await session.commit()
        return redirect(f"/projects/{q.project_id}")
    return redirect("/projects")


@router.post("/queries/{query_id}/delete")
async def query_delete(
    query_id: int,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if user is None:
        return redirect("/login")
    q = await session.get(Query, query_id)
    pid = q.project_id if q else None
    if q and is_admin(user):
        await session.delete(q)
        await session.commit()
    return redirect(f"/projects/{pid}" if pid else "/projects")


# ── Сайты ──────────────────────────────────────────────────────────────────
@router.post("/projects/{project_id}/sites")
async def sites_add(
    project_id: int,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    name: str = Form(...),
    url: str = Form(""),
    match_mode: str = Form("domain"),
):
    if user is None:
        return redirect("/login")
    if is_admin(user) and name.strip():
        domain = normalize_host(url) or normalize_host(name)
        session.add(Site(
            project_id=project_id, name=name.strip(), url=url.strip() or None,
            domain=domain, match_mode=match_mode,
        ))
        await session.commit()
    return redirect(f"/projects/{project_id}")


@router.post("/sites/{site_id}/toggle")
async def site_toggle(
    site_id: int,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if user is None:
        return redirect("/login")
    s = await session.get(Site, site_id)
    if s and is_admin(user):
        s.active = not s.active
        await session.commit()
        return redirect(f"/projects/{s.project_id}")
    return redirect("/projects")


@router.post("/sites/{site_id}/delete")
async def site_delete(
    site_id: int,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if user is None:
        return redirect("/login")
    s = await session.get(Site, site_id)
    pid = s.project_id if s else None
    if s and is_admin(user):
        await session.delete(s)
        await session.commit()
    return redirect(f"/projects/{pid}" if pid else "/projects")


# ── Профили ────────────────────────────────────────────────────────────────
@router.post("/projects/{project_id}/profiles")
async def profiles_add(
    project_id: int,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    name: str = Form(...),
    device: str = Form("desktop"),
    source: str = Form("api"),
    region: str = Form("Екатеринбург"),
):
    if user is None:
        return redirect("/login")
    if is_admin(user) and name.strip():
        session.add(Profile(
            project_id=project_id, name=name.strip(), device=device,
            source=source, region=region.strip() or None,
        ))
        await session.commit()
    return redirect(f"/projects/{project_id}")


@router.post("/profiles/{profile_id}/toggle")
async def profile_toggle(
    profile_id: int,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if user is None:
        return redirect("/login")
    p = await session.get(Profile, profile_id)
    if p and is_admin(user):
        p.active = not p.active
        await session.commit()
        return redirect(f"/projects/{p.project_id}")
    return redirect("/projects")


@router.post("/profiles/{profile_id}/delete")
async def profile_delete(
    profile_id: int,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if user is None:
        return redirect("/login")
    p = await session.get(Profile, profile_id)
    pid = p.project_id if p else None
    if p and is_admin(user):
        await session.delete(p)
        await session.commit()
    return redirect(f"/projects/{pid}" if pid else "/projects")


# ── Проверить сейчас ───────────────────────────────────────────────────────
@router.post("/projects/{project_id}/run")
async def project_run_now(
    project_id: int,
    request: Request,
    user: User | None = Depends(current_user),
    mode: str = Form(RunMode.SEO.value),
):
    if user is None:
        return redirect("/login")
    if is_admin(user):
        settings = request.app.state.settings
        maker = get_sessionmaker()

        async def _job():
            try:
                summary = await run_project_batch(maker, settings, project_id, mode=mode)
                logger.info("Ручной прогон проекта %s (%s): %s", project_id, mode, summary)
            except Exception:  # noqa: BLE001
                logger.exception("Ручной прогон проекта %s упал", project_id)

        asyncio.create_task(_job())
    return redirect(f"/projects/{project_id}?mode={mode}")
