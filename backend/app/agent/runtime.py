"""Рантайм активных запусков агента.

Один RunState на активную задачу. Хранит:
- флаг остановки (Stop Agent) и убийство дочерних process groups;
- ожидающие подтверждения (пауза цикла до ответа из UI);
- накопленный расход токенов.

RunRegistry — потокобезопасный (в рамках одного event loop) словарь по session_id.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_tokens: int = 0

    def add(self, inp: int, out: int, cache_hit: int) -> None:
        self.input_tokens += inp
        self.output_tokens += out
        self.cache_hit_tokens += cache_hit


@dataclass
class RunState:
    session_id: str
    stop_requested: bool = False
    _process_groups: set[int] = field(default_factory=set)
    # call_id -> Future[bool]: True = разрешить, False = отменить
    _pending: dict[str, asyncio.Future] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)

    # --- Процессы (для Stop Agent) ---
    def register_process(self, pgid: int) -> None:
        self._process_groups.add(pgid)

    def unregister_process(self, pgid: int) -> None:
        self._process_groups.discard(pgid)

    def kill_processes(self) -> None:
        from ..tools.terminal import kill_run_processes
        kill_run_processes(self._process_groups)
        self._process_groups.clear()

    # --- Остановка ---
    def request_stop(self) -> None:
        self.stop_requested = True
        self.kill_processes()
        # Отменяем все ожидающие подтверждения как "cancel".
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_result(False)

    # --- Подтверждения ---
    def create_confirmation(self, call_id: str) -> asyncio.Future:
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[call_id] = fut
        return fut

    def resolve_confirmation(self, call_id: str, approved: bool) -> bool:
        fut = self._pending.get(call_id)
        if fut is None or fut.done():
            return False
        fut.set_result(approved)
        return True


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}

    def create(self, session_id: str) -> RunState:
        # Если предыдущий запуск для сессии ещё жив — останавливаем его.
        old = self._runs.get(session_id)
        if old is not None:
            old.request_stop()
        run = RunState(session_id=session_id)
        self._runs[session_id] = run
        return run

    def get(self, session_id: str) -> RunState | None:
        return self._runs.get(session_id)

    def stop(self, session_id: str) -> bool:
        run = self._runs.get(session_id)
        if run is None:
            return False
        run.request_stop()
        return True

    def confirm(self, session_id: str, call_id: str, approved: bool) -> bool:
        run = self._runs.get(session_id)
        if run is None:
            return False
        return run.resolve_confirmation(call_id, approved)

    def finish(self, session_id: str, run: RunState) -> None:
        # Удаляем, только если это тот же самый запуск.
        if self._runs.get(session_id) is run:
            self._runs.pop(session_id, None)


# Единый реестр на процесс.
registry = RunRegistry()
