"""Фоновые задачи агента, отвязанные от HTTP-соединения.

Зачем: раньше цикл агента жил внутри SSE-генератора запроса `POST /api/chat`.
Если браузер закрывал вкладку (или рвалась сеть), Starlette отменял генератор —
и агент умирал на полпути, оставляя работу недоделанной.

Теперь:
- агент запускается отдельной задачей (`asyncio.Task`) и живёт сам по себе;
- все события складываются в буфер с порядковыми номерами (`seq`);
- HTTP-ответ лишь **подписывается** на буфер: закрытие вкладки отписывает
  клиента, но не останавливает работу;
- при возврате на страницу клиент переподключается с `from=<последний seq>`
  и получает пропущенные события — как будто никуда не уходил;
- если к моменту завершения никто не смотрит (вкладка закрыта), итог уходит
  в Telegram, чтобы результат не потерялся.

Остановить работу может только явный Stop (`/api/agent/stop`) или лимит шагов.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

log = logging.getLogger(__name__)

# Сколько завершённых задач держим в памяти для переподключения.
MAX_FINISHED = 30
# Как часто отправлять «пинг» в SSE, чтобы прокси не закрыл соединение.
PING_SECONDS = 15


@dataclass
class Job:
    """Один запуск агента: буфер событий + подписчики."""

    conversation_id: str
    project: str
    events: list[dict] = field(default_factory=list)
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    task: asyncio.Task | None = None
    done: bool = False
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    # Итоговый текст — нужен, чтобы переслать его в Telegram, если никто не смотрел.
    final_text: str = ""
    error: str = ""

    # --- Публикация событий ---
    def emit(self, ev: dict[str, Any]) -> None:
        """Добавить событие в буфер и раздать подписчикам."""
        if ev.get("type") == "final":
            self.final_text = ev.get("content", "") or ""
        if ev.get("type") == "error":
            self.error = ev.get("message", "") or ""
        seq_event = {**ev, "seq": len(self.events) + 1}
        self.events.append(seq_event)
        for q in list(self.subscribers):
            q.put_nowait(seq_event)

    def finish(self) -> None:
        if self.done:
            return
        self.done = True
        self.finished_at = time.time()
        # Сигнал подписчикам: событий больше не будет.
        for q in list(self.subscribers):
            q.put_nowait(None)

    # --- Подписка ---
    def subscribe(self, from_seq: int = 0) -> tuple[list[dict], asyncio.Queue]:
        """Вернуть (что уже было, канал новых событий).

        Между снимком буфера и подпиской нет await — гонки нет: событие не
        может «проскочить» незамеченным в одном потоке событий.
        """
        start = max(0, int(from_seq or 0))
        backlog = self.events[start:]
        q: asyncio.Queue = asyncio.Queue()
        if not self.done:
            self.subscribers.add(q)
        return backlog, q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    @property
    def seq(self) -> int:
        return len(self.events)

    @property
    def watching(self) -> bool:
        return bool(self.subscribers)

    def status(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "project": self.project,
            "running": not self.done,
            "done": self.done,
            "seq": self.seq,
            "watching": self.watching,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    async def stream(self, from_seq: int = 0) -> AsyncIterator[dict[str, Any]]:
        """События для одного клиента: сначала пропущенное, затем живое."""
        backlog, q = self.subscribe(from_seq)
        try:
            for ev in backlog:
                yield ev
            if self.done:
                # Задача уже закончилась — явно сообщаем клиенту, что всё.
                if not backlog or backlog[-1].get("type") != "end":
                    yield {"type": "end", "seq": self.seq}
                return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=PING_SECONDS)
                except asyncio.TimeoutError:
                    # Пинг, чтобы nginx/браузер не разорвали соединение.
                    yield {"type": "ping"}
                    continue
                if ev is None:
                    yield {"type": "end", "seq": self.seq}
                    return
                yield ev
        finally:
            # Клиент ушёл — отписываемся. Сама задача продолжает работать.
            self.unsubscribe(q)


class JobRegistry:
    """Все активные и недавно завершённые задачи (по conversation_id)."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def get(self, conversation_id: str) -> Job | None:
        return self._jobs.get(conversation_id)

    def running(self, conversation_id: str) -> bool:
        job = self._jobs.get(conversation_id)
        return bool(job and not job.done)

    def start(
        self,
        conversation_id: str,
        project: str,
        runner: Callable[[Job], AsyncIterator[dict[str, Any]]],
        on_finish: Callable[["Job"], None] | None = None,
    ) -> Job:
        """Запустить задачу в фоне и вернуть её.

        `runner` — async-генератор, отдающий события агента. Он исполняется в
        отдельной задаче, поэтому обрыв HTTP-соединения его не останавливает.
        """
        old = self._jobs.get(conversation_id)
        if old is not None and not old.done and old.task is not None:
            # Новое сообщение в тот же чат: прежнюю работу останавливаем.
            old.task.cancel()

        job = Job(conversation_id=conversation_id, project=project)
        self._jobs[conversation_id] = job
        job.task = asyncio.create_task(self._run(job, runner, on_finish))

        # Чистим старые завершённые задачи, чтобы не копить память.
        finished = sorted((j for j in self._jobs.values() if j.done),
                          key=lambda j: j.finished_at or 0)
        for j in finished[:max(0, len(finished) - MAX_FINISHED)]:
            self._jobs.pop(j.conversation_id, None)
        return job

    @staticmethod
    async def _run(
        job: Job,
        runner: Callable[[Job], AsyncIterator[dict[str, Any]]],
        on_finish: Callable[[Job], None] | None,
    ) -> None:
        try:
            async for ev in runner(job):
                job.emit(ev)
        except asyncio.CancelledError:
            job.emit({"type": "stopped"})
            raise
        except Exception as exc:  # noqa: BLE001 — задача не должна «умирать молча»
            log.exception("фоновая задача агента упала")
            job.emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            job.finish()
            if on_finish is not None:
                try:
                    on_finish(job)
                except Exception:  # noqa: BLE001 — уведомление не должно ломать задачу
                    log.exception("не удалось обработать завершение задачи")

    def cancel(self, conversation_id: str) -> bool:
        job = self._jobs.get(conversation_id)
        if job is None or job.done or job.task is None:
            return False
        job.task.cancel()
        return True

    def forget(self, conversation_id: str) -> None:
        self._jobs.pop(conversation_id, None)

    def active(self) -> list[dict[str, Any]]:
        return [j.status() for j in self._jobs.values() if not j.done]


# Единый реестр на процесс.
jobs = JobRegistry()
