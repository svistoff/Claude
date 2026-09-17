"""Terminal-инструмент: выполнение команд в project root.

Безопасность:
- команда исполняется в отдельной process group, чтобы Stop Agent мог убить
  весь дерево процессов (раздел 20 ТЗ);
- жёсткий timeout (раздел 21 ТЗ);
- классификация опасных команд — в agent/permissions.py; сюда команда приходит
  уже разрешённой (allow) либо подтверждённой пользователем.

Изоляция уровня ОС: сам сервис ai-agent должен работать под отдельным
непривилегированным пользователем (см. deploy/). Опционально — запуск команд в
Docker-контейнере на проект (sandbox: docker в config.yaml).
"""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

from .base import ToolContext, ToolResult

_MAX_OUTPUT = 20000  # символов вывода, возвращаемых модели


def terminal(ctx: ToolContext, command: str, timeout: int | None = None) -> ToolResult:
    agent_cfg = ctx.config.agent
    if timeout is None:
        timeout = agent_cfg.terminal_timeout_default
    timeout = min(int(timeout), agent_cfg.terminal_timeout_max)

    # Проверка флага остановки перед запуском.
    if ctx.run is not None and ctx.run.stop_requested:
        return ToolResult(False, "Остановлено пользователем.", summary="terminal: stopped")

    env = _sanitized_env()

    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=str(ctx.project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            # Новая сессия -> отдельная process group; убиваем по -pgid.
            start_new_session=True,
        )
    except OSError as exc:
        return ToolResult(False, f"Не удалось запустить команду: {exc}",
                          summary="terminal: spawn failed")

    pgid = os.getpgid(proc.pid)
    if ctx.run is not None:
        ctx.run.register_process(pgid)

    try:
        out, _ = proc.communicate(timeout=timeout)
        code = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_group(pgid)
        try:
            out, _ = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out = ""
        code = -1
        timed_out = True
    finally:
        if ctx.run is not None:
            ctx.run.unregister_process(pgid)

    out = out or ""
    if len(out) > _MAX_OUTPUT:
        out = out[:_MAX_OUTPUT] + "\n[...вывод обрезан]"

    if timed_out:
        content = (f"Команда прервана по timeout ({timeout} c):\n$ {command}\n\n"
                   f"Вывод до прерывания:\n{out}")
        return ToolResult(False, content, summary=f"terminal: timeout ({timeout}s)",
                          extra={"command": command, "exit_code": None, "timed_out": True,
                                 "output": out})

    ok = code == 0
    content = f"$ {command}\n[exit {code}]\n{out}"
    return ToolResult(
        ok, content,
        summary=f"terminal: {command[:60]} → exit {code}",
        extra={"command": command, "exit_code": code, "output": out},
    )


def _kill_group(pgid: int) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        except OSError:
            return


def _sanitized_env() -> dict[str, str]:
    """Окружение без секретов приложения (API-ключ, SECRET_KEY и т.п.)."""
    blocked_prefixes = ("DEEPSEEK_", "ADMIN_", "SECRET_", "DATABASE_")
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith(blocked_prefixes) and k not in {"SECRET_KEY"}
    }
    return env


def kill_run_processes(pgids: set[int]) -> None:
    """Убить все зарегистрированные process groups запуска (для Stop Agent)."""
    for pgid in list(pgids):
        _kill_group(pgid)
