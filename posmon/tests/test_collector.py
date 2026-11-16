from sqlalchemy import select

from posmon.domain.results import CheckStatus, ResultType, SerpResult
from posmon.models import Check, CheckRun, PositionHistory, Profile, Project, Query, SearchResult, Site
from posmon.providers.mock import MockProvider
from posmon.services.collector import run_query_check


async def _setup(session, *, is_local=False):
    project = Project(name="ЕКБ ГИД", depth=50)
    session.add(project)
    await session.flush()
    query = Query(project_id=project.id, query="ресторан Екатеринбург", is_local=is_local)
    site_a = Site(project_id=project.id, name="A", domain="site-a.ru", match_mode="domain")
    site_miss = Site(project_id=project.id, name="M", domain="missing.ru", match_mode="domain")
    profile = Profile(project_id=project.id, name="Desktop", device="desktop", source="api")
    session.add_all([query, site_a, site_miss, profile])
    await session.flush()
    return project, query, [site_a, site_miss], profile


def _serp():
    return [
        SerpResult("https://ad.ru", ResultType.AD_TOP),
        SerpResult("https://site-a.ru/x", ResultType.ORGANIC),
        SerpResult("https://other.ru", ResultType.ORGANIC),
    ]


async def test_successful_run_writes_positions_and_history(session):
    project, query, sites, profile = await _setup(session)
    provider = MockProvider(default_serp=_serp())

    run = await run_query_check(
        session, project_id=project.id, query=query, profile=profile, sites=sites,
        provider=provider, depth=50, region_lr=54,
    )
    await session.commit()

    assert run.status == CheckStatus.SUCCESS.value
    assert run.source == "mock"

    # полная выдача сохранена
    results = (await session.execute(select(SearchResult))).scalars().all()
    assert len(results) == 3

    checks = {c.site_id: c for c in (await session.execute(select(Check))).scalars().all()}
    a = next(c for c in checks.values() if c.position == 1)
    assert a.status == CheckStatus.SUCCESS.value
    miss = next(c for c in checks.values() if c.position is None)
    assert miss.status == CheckStatus.NOT_FOUND.value

    history = (await session.execute(select(PositionHistory))).scalars().all()
    assert len(history) == 2  # по одной записи на сайт за сегодня


async def test_error_run_writes_no_positions(session):
    project, query, sites, profile = await _setup(session)
    provider = MockProvider(force_status=CheckStatus.CAPTCHA)

    run = await run_query_check(
        session, project_id=project.id, query=query, profile=profile, sites=sites,
        provider=provider, depth=50, region_lr=54,
    )
    await session.commit()

    assert run.status == CheckStatus.CAPTCHA.value
    assert (await session.execute(select(Check))).scalars().first() is None
    assert (await session.execute(select(SearchResult))).scalars().first() is None
    assert (await session.execute(select(PositionHistory))).scalars().first() is None


async def test_history_upsert_same_day(session):
    project, query, sites, profile = await _setup(session)
    provider = MockProvider(default_serp=_serp())

    await run_query_check(session, project_id=project.id, query=query, profile=profile,
                          sites=sites, provider=provider, depth=50, region_lr=54)
    await run_query_check(session, project_id=project.id, query=query, profile=profile,
                          sites=sites, provider=provider, depth=50, region_lr=54)
    await session.commit()

    # два прогона за день -> история всё равно одна запись на сайт
    history = (await session.execute(select(PositionHistory))).scalars().all()
    assert len(history) == 2
    runs = (await session.execute(select(CheckRun))).scalars().all()
    assert len(runs) == 2  # но оба прогона сохранены (история проверок не теряется)


async def test_battle_mode_records_visual_and_ads(session):
    project, query, sites, profile = await _setup(session)
    serp = [
        SerpResult("https://ad1.ru", ResultType.AD_TOP),
        SerpResult("https://ad2.ru", ResultType.AD_TOP),
        SerpResult("https://site-a.ru/x", ResultType.ORGANIC),  # органика #1, визуально #3
    ]
    provider = MockProvider(default_serp=serp)

    await run_query_check(
        session, project_id=project.id, query=query, profile=profile, sites=sites,
        provider=provider, depth=50, region_lr=54, mode="battle",
    )
    await session.commit()

    a = (await session.execute(
        select(Check).where(Check.site_id == sites[0].id)
    )).scalar_one()
    assert a.position == 1          # органика
    assert a.visual_position == 3   # с учётом 2 реклам сверху
    assert a.ads_above == 2

    hist = (await session.execute(
        select(PositionHistory).where(PositionHistory.site_id == sites[0].id)
    )).scalar_one()
    assert hist.mode == "battle"
    assert hist.visual_position == 3


async def test_seo_and_battle_history_are_separate(session):
    project, query, sites, profile = await _setup(session)
    provider = MockProvider(default_serp=_serp())

    await run_query_check(session, project_id=project.id, query=query, profile=profile,
                          sites=sites, provider=provider, depth=50, region_lr=54, mode="seo")
    await run_query_check(session, project_id=project.id, query=query, profile=profile,
                          sites=sites, provider=provider, depth=50, region_lr=54, mode="battle")
    await session.commit()

    # для одного сайта за день — 2 записи истории: seo и battle раздельно
    rows = (await session.execute(
        select(PositionHistory).where(PositionHistory.site_id == sites[0].id)
    )).scalars().all()
    assert {r.mode for r in rows} == {"seo", "battle"}


async def test_local_query_tracks_business_position(session):
    project, query, sites, profile = await _setup(session, is_local=True)
    serp = [
        SerpResult("https://site-a.ru", ResultType.BUSINESS),  # в блоке Бизнеса #1
        SerpResult("https://site-a.ru/org", ResultType.ORGANIC),  # органика #1
    ]
    provider = MockProvider(default_serp=serp)
    await run_query_check(session, project_id=project.id, query=query, profile=profile,
                          sites=sites, provider=provider, depth=50, region_lr=54)
    await session.commit()

    a = (await session.execute(
        select(Check).where(Check.site_id == sites[0].id)
    )).scalar_one()
    assert a.position == 1
    assert a.business_position == 1
