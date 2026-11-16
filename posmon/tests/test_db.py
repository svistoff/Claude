from datetime import datetime, timezone

from sqlalchemy import select

from posmon.models import (
    Check,
    CheckRun,
    Profile,
    Project,
    Query,
    SearchResult,
    Site,
)


async def test_schema_roundtrip(session):
    project = Project(name="ЕКБ ГИД", depth=50)
    session.add(project)
    await session.flush()

    query = Query(project_id=project.id, query="ресторан Екатеринбург", is_local=True)
    site = Site(project_id=project.id, name="ЕКБ ГИД", domain="ekb-guide.ru", match_mode="domain")
    profile = Profile(project_id=project.id, name="Desktop", device="desktop", source="api")
    session.add_all([query, site, profile])
    await session.flush()

    run = CheckRun(
        project_id=project.id,
        query_id=query.id,
        profile_id=profile.id,
        source="api",
        status="SUCCESS",
        started_at=datetime.now(timezone.utc),
    )
    session.add(run)
    await session.flush()

    session.add(
        SearchResult(
            check_run_id=run.id,
            position=1,
            url="https://ekb-guide.ru/",
            domain="ekb-guide.ru",
            result_type="organic",
        )
    )
    session.add(
        Check(
            check_run_id=run.id,
            project_id=project.id,
            query_id=query.id,
            site_id=site.id,
            profile_id=profile.id,
            checked_at=datetime.now(timezone.utc),
            position=1,
            business_position=None,
            status="SUCCESS",
        )
    )
    await session.commit()

    got = (await session.execute(select(Check))).scalar_one()
    assert got.position == 1
    assert got.status == "SUCCESS"

    results = (await session.execute(select(SearchResult))).scalars().all()
    assert len(results) == 1
    assert results[0].domain == "ekb-guide.ru"
