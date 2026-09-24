"""Менеджер браузера (Фаза 3): Playwright в отдельном потоке.

Все вызовы Playwright выполняются на одном выделенном потоке (объекты Playwright
привязаны к потоку). Инструменты шлют команды через очередь и ждут результат.

Изоляция: свежий headless-контекст без пользовательского профиля (не личный Chrome).
Скриншоты сохраняются в WORKSPACE_TMP/screenshots и отдаются в UI отдельным роутом.
"""

from __future__ import annotations

import queue
import threading
import uuid
from pathlib import Path
from typing import Any

from .config import BACKEND_DIR, get_app_config, get_settings


def screenshots_dir() -> Path:
    tmp = get_settings().workspace_tmp
    p = Path(tmp)
    if not p.is_absolute():
        p = BACKEND_DIR / p
    d = (p / "screenshots").resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


class BrowserManager:
    """Одна вкладка на процесс (один админ). Ленивая инициализация."""

    def __init__(self) -> None:
        self._cmd_q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._start_error: str | None = None
        self._lock = threading.Lock()

    # --- Публичный API ---
    def available(self) -> tuple[bool, str]:
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False, "Playwright не установлен (pip install playwright + playwright install chromium)."
        if not get_app_config().browser.enabled:
            return False, "Браузер выключен в конфигурации."
        return True, ""

    def execute(self, action: str, args: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        ok, reason = self.available()
        if not ok:
            return {"ok": False, "error": reason}
        if not self._ensure_started():
            return {"ok": False, "error": self._start_error or "Браузер не запустился."}
        resp: queue.Queue = queue.Queue(maxsize=1)
        self._cmd_q.put((action, args, resp))
        try:
            return resp.get(timeout=timeout)
        except queue.Empty:
            return {"ok": False, "error": "Таймаут ожидания браузера."}

    def shutdown(self) -> None:
        if self._thread and self._thread.is_alive():
            resp: queue.Queue = queue.Queue(maxsize=1)
            self._cmd_q.put(("__quit__", {}, resp))
            try:
                resp.get(timeout=10)
            except queue.Empty:
                pass
        self._thread = None
        self._ready.clear()

    # --- Внутреннее ---
    def _ensure_started(self) -> bool:
        with self._lock:
            if self._thread and self._thread.is_alive() and self._ready.is_set():
                return True
            self._ready.clear()
            self._start_error = None
            self._thread = threading.Thread(target=self._run, daemon=True, name="browser")
            self._thread.start()
        self._ready.wait(timeout=60)
        return self._ready.is_set() and self._start_error is None

    def _run(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            self._start_error = f"Playwright недоступен: {exc}"
            self._ready.set()
            return

        cfg = get_app_config().browser
        exe = get_settings().browser_executable_path or None
        try:
            with sync_playwright() as p:
                launch_kwargs: dict[str, Any] = {"headless": cfg.headless,
                                                 "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
                if exe:
                    launch_kwargs["executable_path"] = exe
                browser = p.chromium.launch(**launch_kwargs)
                context = browser.new_context(viewport={"width": 1280, "height": 800})
                context.set_default_timeout(cfg.action_timeout_ms)
                page = context.new_page()
                self._ready.set()
                self._loop(page, cfg)
                context.close()
                browser.close()
        except Exception as exc:  # noqa: BLE001
            self._start_error = f"Не удалось запустить браузер: {exc}"
            self._ready.set()

    def _loop(self, page, cfg) -> None:
        while True:
            action, args, resp = self._cmd_q.get()
            if action == "__quit__":
                resp.put({"ok": True})
                return
            try:
                resp.put(self._do(page, cfg, action, args))
            except Exception as exc:  # noqa: BLE001 — ошибку возвращаем, поток не роняем
                resp.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    def _do(self, page, cfg, action: str, a: dict) -> dict:
        if action == "open":
            page.goto(a["url"], wait_until="domcontentloaded", timeout=cfg.nav_timeout_ms)
            return {"ok": True, "url": page.url, "title": page.title()}
        if action == "click":
            if a.get("text"):
                page.get_by_text(a["text"], exact=False).first.click(timeout=cfg.action_timeout_ms)
            else:
                page.click(a["selector"], timeout=cfg.action_timeout_ms)
            return {"ok": True, "url": page.url}
        if action == "type":
            page.fill(a["selector"], a.get("text", ""), timeout=cfg.action_timeout_ms)
            return {"ok": True}
        if action == "select":
            page.select_option(a["selector"], a.get("value"), timeout=cfg.action_timeout_ms)
            return {"ok": True}
        if action == "get_text":
            sel = a.get("selector")
            text = page.inner_text(sel) if sel else page.inner_text("body")
            return {"ok": True, "text": text[:8000], "url": page.url, "title": page.title()}
        if action == "scroll":
            page.mouse.wheel(0, int(a.get("dy", 800)))
            return {"ok": True}
        if action == "back":
            page.go_back(timeout=cfg.nav_timeout_ms)
            return {"ok": True, "url": page.url}
        if action == "wait":
            if a.get("selector"):
                page.wait_for_selector(a["selector"], timeout=cfg.action_timeout_ms)
            else:
                page.wait_for_timeout(int(a.get("ms", 1000)))
            return {"ok": True}
        if action == "screenshot":
            sid = uuid.uuid4().hex[:16]
            path = screenshots_dir() / f"{sid}.png"
            page.screenshot(path=str(path), full_page=bool(a.get("full_page", False)))
            return {"ok": True, "screenshot_id": sid, "path": str(path),
                    "url": page.url, "title": page.title()}
        return {"ok": False, "error": f"Неизвестное действие браузера: {action}"}


# Единый менеджер на процесс.
manager = BrowserManager()
