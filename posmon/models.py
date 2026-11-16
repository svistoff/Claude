"""ORM-модели (схема БД, раздел 6 ТЗ v2).

Ключевые сущности:
- check_runs   — единица работы: одна выборка выдачи (запрос × профиль);
- search_results — полная выдача прогона (для аудита и пересчёта позиции);
- checks       — вычисленная позиция сайта в прогоне (органика + блок Бизнеса);
- position_history — денормализованный слой для графиков/сравнений.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, created_at_column, updated_at_column

# ── Значения-константы (хранятся строками для переносимости SQLite/PG) ──────
# role:        Admin | Viewer
# source:      api | browser
# match_mode:  domain | exact_host
# status:      QUEUED|RUNNING|SUCCESS|NOT_FOUND|ERROR|BLOCKED|CAPTCHA
# result_type: organic|ad_top|ad_bottom|business|maps|video|images|market|fast_answer|other


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, default=50, nullable=False)  # глубина мониторинга
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    queries: Mapped[list["Query"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    sites: Mapped[list["Site"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    profiles: Mapped[list["Profile"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Query(Base):
    __tablename__ = "queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(String(512), nullable=False)
    group_name: Mapped[str | None] = mapped_column(String(255))
    priority: Mapped[str | None] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_local: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # трекать блок Бизнеса
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    project: Mapped[Project] = relationship(back_populates="queries")


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1024))
    domain: Mapped[str] = mapped_column(String(255), nullable=False)  # нормализованный домен
    match_mode: Mapped[str] = mapped_column(String(16), default="domain", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    project: Mapped[Project] = relationship(back_populates="sites")


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str | None] = mapped_column(String(64))
    region: Mapped[str | None] = mapped_column(String(64))
    device: Mapped[str] = mapped_column(String(32), default="desktop", nullable=False)  # desktop|mobile
    browser: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16), default="api", nullable=False)  # api|browser
    browser_profile_path: Mapped[str | None] = mapped_column(String(1024))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    settings_json: Mapped[str | None] = mapped_column(Text)  # секреты/cookies — в зашифрованном виде
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    project: Mapped[Project] = relationship(back_populates="profiles")


class CheckRun(Base):
    """Единица работы: одна выборка выдачи (запрос × профиль)."""

    __tablename__ = "check_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    query_id: Mapped[int] = mapped_column(ForeignKey("queries.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # api|browser
    mode: Mapped[str] = mapped_column(String(16), default="seo", nullable=False)  # seo|battle
    search_url: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[str | None] = mapped_column(String(32))
    screenshot_path: Mapped[str | None] = mapped_column(String(1024))
    raw_html_path: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = created_at_column()

    results: Mapped[list["SearchResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    checks: Mapped[list["Check"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_check_runs_query_profile_time", "query_id", "profile_id", "started_at"),
    )


class SearchResult(Base):
    """Полная выдача прогона (все результаты, для аудита и пересчёта позиции)."""

    __tablename__ = "search_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    check_run_id: Mapped[int] = mapped_column(
        ForeignKey("check_runs.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # порядок в полной выдаче
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(Text)
    result_type: Mapped[str] = mapped_column(String(32), default="organic", nullable=False)
    raw_data: Mapped[str | None] = mapped_column(Text)

    run: Mapped[CheckRun] = relationship(back_populates="results")


class Check(Base):
    """Вычисленная позиция одного сайта в одном прогоне."""

    __tablename__ = "checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    check_run_id: Mapped[int] = mapped_column(
        ForeignKey("check_runs.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    query_id: Mapped[int] = mapped_column(ForeignKey("queries.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    position: Mapped[int | None] = mapped_column(Integer)           # органика, NULL если не найден
    business_position: Mapped[int | None] = mapped_column(Integer)  # блок Бизнеса, NULL/для локальных
    visual_position: Mapped[int | None] = mapped_column(Integer)    # боевой режим: номер с учётом рекламы
    ads_above: Mapped[int | None] = mapped_column(Integer)          # боевой режим: реклам над сайтом
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    run: Mapped[CheckRun] = relationship(back_populates="checks")


class PositionHistory(Base):
    """Денормализованный слой для графиков и сравнений периодов."""

    __tablename__ = "position_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    query_id: Mapped[int] = mapped_column(ForeignKey("queries.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), default="seo", nullable=False)  # seo|battle
    position: Mapped[int | None] = mapped_column(Integer)
    business_position: Mapped[int | None] = mapped_column(Integer)
    visual_position: Mapped[int | None] = mapped_column(Integer)
    ads_above: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "query_id", "site_id", "profile_id", "date", "mode",
            name="uq_position_history_daily",
        ),
    )


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    period_start: Mapped[datetime] = mapped_column(Date, nullable=False)
    period_end: Mapped[datetime] = mapped_column(Date, nullable=False)
    params_json: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(String(1024))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at_column()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    query_id: Mapped[int | None] = mapped_column(ForeignKey("queries.id", ondelete="CASCADE"))
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # rise|drop|left_top10|...
    old_position: Mapped[int | None] = mapped_column(Integer)
    new_position: Mapped[int | None] = mapped_column(Integer)
    delta: Mapped[int | None] = mapped_column(Integer)
    channel: Mapped[str | None] = mapped_column(String(32))  # telegram|email
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    login: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="Viewer", nullable=False)  # Admin|Viewer
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # create|update|delete|run|report
    diff_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
