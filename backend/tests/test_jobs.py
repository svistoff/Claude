"""Тесты фоновых задач агента: работа не прерывается при закрытии вкладки.

Проверяем главное обещание: обрыв SSE-подписки (закрытая вкладка) НЕ
останавливает агента, а вернувшись, клиент получает все пропущенные события.
"""

from __future__ import annotations

import asyncio

from app.agent.jobs import Job, JobRegistry


def run(coro):
    return asyncio.run(coro)


def _make_runner(events: list[dict], delay: float = 0.0):
    """Async-генератор событий с паузами (имитация долгой работы)."""
    async def runner(job):
        for ev in events:
            if delay:
                await asyncio.sleep(delay)
            yield ev
    return runner


# --- Буфер и нумерация --------------------------------------------------------

def test_emit_assigns_seq():
    job = Job(conversation_id="c1", project="p")
    job.emit({"type": "text", "delta": "а"})
    job.emit({"type": "text", "delta": "б"})
    assert [e["seq"] for e in job.events] == [1, 2]
    assert job.seq == 2


def test_final_and_error_are_captured():
    job = Job(conversation_id="c1", project="p")
    job.emit({"type": "final", "content": "готово"})
    assert job.final_text == "готово"
    job.emit({"type": "error", "message": "сломалось"})
    assert job.error == "сломалось"


# --- Задача продолжается без подписчиков --------------------------------------

def test_job_runs_without_any_subscriber():
    """Никто не подключён — работа всё равно доходит до конца."""
    reg = JobRegistry()
    events = [{"type": "text", "delta": "шаг"}, {"type": "final", "content": "итог"}]

    async def scenario():
        job = reg.start("c1", "proj", _make_runner(events))
        await job.task  # ждём завершения фоновой задачи
        return job

    job = run(scenario())
    assert job.done
    assert job.final_text == "итог"
    assert [e["type"] for e in job.events] == ["text", "final"]


def test_disconnect_does_not_cancel_job():
    """Клиент отписался посреди работы — задача продолжается."""
    reg = JobRegistry()
    events = [{"type": "text", "delta": str(i)} for i in range(5)] + \
             [{"type": "final", "content": "готово"}]

    async def scenario():
        job = reg.start("c1", "proj", _make_runner(events, delay=0.01))
        # Подключаемся, читаем 2 события и «закрываем вкладку».
        stream = job.stream()
        got = []
        got.append(await stream.__anext__())
        got.append(await stream.__anext__())
        await stream.aclose()            # разрыв соединения
        assert not job.watching          # подписчиков нет
        await job.task                   # а работа идёт дальше
        return job, got

    job, got = run(scenario())
    assert len(got) == 2
    assert job.done and job.final_text == "готово"
    assert job.seq == len(events)


def test_reconnect_replays_missed_events():
    """Вернувшись с from=2, клиент получает всё, что пропустил."""
    reg = JobRegistry()
    events = [{"type": "text", "delta": d} for d in ("а", "б", "в", "г")]

    async def scenario():
        job = reg.start("c1", "proj", _make_runner(events))
        await job.task
        return [ev async for ev in job.stream(from_seq=2)]

    got = run(scenario())
    types_deltas = [(e["type"], e.get("delta")) for e in got]
    assert types_deltas[:2] == [("text", "в"), ("text", "г")]
    # В конце — сигнал завершения, чтобы клиент снял «выполняется».
    assert got[-1]["type"] == "end"


def test_stream_of_finished_job_ends_immediately():
    reg = JobRegistry()

    async def scenario():
        job = reg.start("c1", "proj", _make_runner([{"type": "final", "content": "ок"}]))
        await job.task
        return [ev async for ev in job.stream(from_seq=0)]

    got = run(scenario())
    assert got[-1]["type"] == "end"


# --- Управление задачами ------------------------------------------------------

def test_new_message_in_same_chat_cancels_previous():
    reg = JobRegistry()

    async def scenario():
        first = reg.start("c1", "proj", _make_runner([{"type": "text", "delta": "1"}] * 50,
                                                     delay=0.05))
        await asyncio.sleep(0.01)
        second = reg.start("c1", "proj", _make_runner([{"type": "final", "content": "новое"}]))
        await asyncio.sleep(0.05)
        return first, second

    first, second = run(scenario())
    assert first.task.cancelled() or first.done
    assert second.final_text == "новое"


def test_cancel_marks_stopped():
    reg = JobRegistry()

    async def scenario():
        job = reg.start("c1", "proj", _make_runner([{"type": "text", "delta": "x"}] * 50,
                                                   delay=0.05))
        await asyncio.sleep(0.01)
        reg.cancel("c1")
        try:
            await job.task
        except asyncio.CancelledError:
            pass
        return job

    job = run(scenario())
    assert any(e["type"] == "stopped" for e in job.events)


def test_cancel_unknown_job_returns_false():
    assert JobRegistry().cancel("нет такого") is False


def test_on_finish_callback_receives_job():
    reg = JobRegistry()
    seen = {}

    def on_finish(job):
        seen["final"] = job.final_text

    async def scenario():
        job = reg.start("c1", "proj", _make_runner([{"type": "final", "content": "итог"}]),
                        on_finish=on_finish)
        await job.task

    run(scenario())
    assert seen["final"] == "итог"


def test_runner_exception_becomes_error_event():
    reg = JobRegistry()

    async def boom(job):
        yield {"type": "text", "delta": "начало"}
        raise RuntimeError("сломалось на середине")

    async def scenario():
        job = reg.start("c1", "proj", boom)
        await job.task
        return job

    job = run(scenario())
    assert job.done
    errs = [e for e in job.events if e["type"] == "error"]
    assert errs and "сломалось на середине" in errs[0]["message"]


def test_active_lists_only_running():
    reg = JobRegistry()

    async def scenario():
        running = reg.start("c1", "proj", _make_runner([{"type": "text", "delta": "x"}] * 10,
                                                      delay=0.05))
        done = reg.start("c2", "proj", _make_runner([{"type": "final", "content": "ок"}]))
        await done.task
        active = reg.active()
        running.task.cancel()
        return active

    active = run(scenario())
    ids = {a["conversation_id"] for a in active}
    assert ids == {"c1"}
