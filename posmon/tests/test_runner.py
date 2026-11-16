from sqlalchemy import select

from posmon.config import Settings
from posmon.domain.results import CheckStatus, ResultType, SerpResult
from posmon.models import CheckRun, Profile, Project, Query, Site
from posmon.providers.base import SerpFetch
from posmon.providers.mock import MockProvider
from posmon.services.runner import run_project_batch


def _settings(**kw):
    base = dict(workers=2, max_attempts=2, region_lr=54, timezone="Asia/Yekaterinburg")
    base.update(kw)
    return Settings(_env_file=None, **base)


async def _noop_sleep(_seconds):
    return None


def _serp():
    return [SerpResult("https://site-a.ru/x", ResultType.ORGANIC)]


async def _make_project(maker, *, n_queries=2, n_profiles=2):
    async with maker() as s:
        project = Project(name="P", depth=50)
        s.add(project)
        await s.flush()
        for i in range(n_queries):
            s.add(Query(project_id=project.id, query=f"q{i}", active=True))
        for i in range(n_profiles):
            s.add(Profile(project_id=project.id, name=f"pr{i}", device="desktop", source="api"))
        s.add(Site(project_id=project.id, name="A", domain="site-a.ru", match_mode="domain"))
        await s.commit()
        return project.id


async def test_batch_runs_all_pairs(db_maker):
    project_id = await _make_project(db_maker, n_queries=2, n_profiles=2)
    factory = lambda profile, settings: MockProvider(default_serp=_serp())  # noqa: E731

    summary = await run_project_batch(
        db_maker, _settings(), project_id,
        provider_factory=factory, sleeper=_noop_sleep,
    )
    assert summary.total == 4          # 2 запроса × 2 профиля
    assert summary.success == 4
    assert summary.failed == 0


async def test_failure_retries_then_fails(db_maker):
    project_id = await _make_project(db_maker, n_queries=1, n_profiles=1)
    factory = lambda profile, settings: MockProvider(force_status=CheckStatus.CAPTCHA)  # noqa: E731

    summary = await run_project_batch(
        db_maker, _settings(max_attempts=3), project_id,
        provider_factory=factory, sleeper=_noop_sleep,
    )
    assert summary.total == 1
    assert summary.failed == 1
    # 3 попытки -> 3 записи CheckRun
    async with db_maker() as s:
        runs = (await s.execute(select(CheckRun))).scalars().all()
        assert len(runs) == 3


async def test_retry_then_success(db_maker):
    project_id = await _make_project(db_maker, n_queries=1, n_profiles=1)

    class FlakyProvider:
        source = "mock"

        def __init__(self):
            self.calls = 0

        async def fetch(self, request):
            self.calls += 1
            if self.calls == 1:
                return SerpFetch(status=CheckStatus.ERROR, source="mock", error_code="temp")
            return SerpFetch(status=CheckStatus.SUCCESS, source="mock", results=_serp())

    flaky = FlakyProvider()
    factory = lambda profile, settings: flaky  # noqa: E731

    summary = await run_project_batch(
        db_maker, _settings(max_attempts=3), project_id,
        provider_factory=factory, sleeper=_noop_sleep,
    )
    assert summary.success == 1
    assert flaky.calls == 2   # упал один раз, со второй попытки успех


async def test_unconfigured_provider_records_error(db_maker):
    project_id = await _make_project(db_maker, n_queries=1, n_profiles=1)

    def factory(profile, settings):
        raise ValueError("не настроен")

    summary = await run_project_batch(
        db_maker, _settings(), project_id,
        provider_factory=factory, sleeper=_noop_sleep,
    )
    assert summary.failed == 1
    async with db_maker() as s:
        run = (await s.execute(select(CheckRun))).scalar_one()
        assert run.status == CheckStatus.ERROR.value
        assert run.error_code == "provider_unconfigured"
