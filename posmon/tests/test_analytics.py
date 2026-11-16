from datetime import date, timedelta

from posmon.models import PositionHistory, Profile, Project, Query, Site
from posmon.services.analytics import (
    avg_position_series,
    heatmap_matrix,
    history_series,
    latest_positions,
    site_metrics,
)


async def _seed(session):
    project = Project(name="P", depth=50)
    session.add(project)
    await session.flush()
    q = Query(project_id=project.id, query="q1")
    s = Site(project_id=project.id, name="A", domain="a.ru")
    p = Profile(project_id=project.id, name="Desktop", source="api")
    session.add_all([q, s, p])
    await session.flush()
    return project, q, s, p


async def test_latest_positions_picks_most_recent(session):
    project, q, s, p = await _seed(session)
    today = date.today()
    for d, pos in [(today - timedelta(days=2), 8), (today, 4)]:
        session.add(PositionHistory(project_id=project.id, query_id=q.id, site_id=s.id,
                                    profile_id=p.id, date=d, mode="seo", position=pos, status="SUCCESS"))
    await session.commit()

    latest = await latest_positions(session, project.id, "seo")
    assert latest[(q.id, s.id, p.id)].position == 4  # свежая, не 8


async def test_history_series_by_profile(session):
    project, q, s, p = await _seed(session)
    today = date.today()
    session.add(PositionHistory(project_id=project.id, query_id=q.id, site_id=s.id,
                                profile_id=p.id, date=today, mode="seo", position=5, status="SUCCESS"))
    await session.commit()

    series = await history_series(session, query_id=q.id, site_id=s.id, mode="seo", days=30)
    assert p.id in series
    assert series[p.id][-1][1] == 5


async def test_site_metrics_excludes_not_found(session):
    project, q, s, p = await _seed(session)
    q2 = Query(project_id=project.id, query="q2")
    session.add(q2)
    await session.flush()
    today = date.today()
    session.add(PositionHistory(project_id=project.id, query_id=q.id, site_id=s.id,
                                profile_id=p.id, date=today, mode="seo", position=3, status="SUCCESS"))
    session.add(PositionHistory(project_id=project.id, query_id=q2.id, site_id=s.id,
                                profile_id=p.id, date=today, mode="seo", position=None, status="NOT_FOUND"))
    await session.commit()

    m = await site_metrics(session, site_id=s.id, profile_id=p.id, mode="seo")
    assert m.total == 2
    assert m.found == 1
    assert m.average == 3.0
    assert m.top[3] == 1


async def test_heatmap_matrix(session):
    project, q, s, p = await _seed(session)
    q2 = Query(project_id=project.id, query="a-query")
    session.add(q2)
    await session.flush()
    today = date.today()
    session.add(PositionHistory(project_id=project.id, query_id=q.id, site_id=s.id,
                                profile_id=p.id, date=today, mode="seo", position=4, status="SUCCESS"))
    session.add(PositionHistory(project_id=project.id, query_id=q2.id, site_id=s.id,
                                profile_id=p.id, date=today, mode="seo", position=None, status="NOT_FOUND"))
    await session.commit()

    dates, queries, matrix = await heatmap_matrix(session, site_id=s.id, profile_id=p.id, mode="seo")
    assert dates == [today]
    # запросы отсортированы по тексту: "a-query" раньше "q1"
    assert [name for _, name in queries] == ["a-query", "q1"]
    assert matrix[q.id][today] == 4
    assert matrix[q2.id][today] is None


async def test_avg_position_series(session):
    project, q, s, p = await _seed(session)
    q2 = Query(project_id=project.id, query="q2")
    session.add(q2)
    await session.flush()
    today = date.today()
    # два запроса: позиции 4 и 6 -> средняя 5.0; один NOT_FOUND не учитывается
    session.add(PositionHistory(project_id=project.id, query_id=q.id, site_id=s.id,
                                profile_id=p.id, date=today, mode="seo", position=4, status="SUCCESS"))
    session.add(PositionHistory(project_id=project.id, query_id=q2.id, site_id=s.id,
                                profile_id=p.id, date=today, mode="seo", position=6, status="SUCCESS"))
    await session.commit()

    dates, matrix, names = await avg_position_series(
        session, project_id=project.id, profile_id=p.id, mode="seo", days=30
    )
    assert dates == [today]
    assert matrix[s.id][today] == 5.0
    assert names[s.id] == "A"
