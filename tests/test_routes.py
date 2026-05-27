import asyncio

from fastapi.testclient import TestClient
from urllib.parse import urlencode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database import Base, get_session
from main import app
from models import AnswerKey
from services.image_hash import ImageFingerprint


def test_home_route_renders():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Paper 1 Response Sheet URL" in response.text


def test_admin_requires_basic_auth():
    with TestClient(app) as client:
        response = client.get("/admin")
    assert response.status_code == 401


def test_admin_option_picker_requires_basic_auth():
    with TestClient(app) as client:
        response = client.post("/admin/option-picker", data={"paper1_url": "p1", "paper2_url": "p2"})
    assert response.status_code == 401


def test_missing_analysis_returns_404():
    with TestClient(app) as client:
        response = client.get("/analysis/does-not-exist")
    assert response.status_code == 404


def test_admin_option_key_refuses_missing_answer_key():
    engine, session_factory = _test_session_factory()
    app.dependency_overrides[get_session] = _override_session(session_factory)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/admin/option-key",
                auth=("admin", "change-me"),
                data={"paper": "1", "question_id": "missing", "selected_image_url": "https://example.test/a.png"},
            )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_admin_option_key_saves_mcq_and_msq_hashes(monkeypatch):
    async def fake_fingerprint_urls(urls):
        return {
            "https://example.test/a.png": ImageFingerprint(md5="md5-a", phash="0000000000000000"),
            "https://example.test/c.png": ImageFingerprint(md5="md5-c", phash="00000000000000ff"),
        }

    monkeypatch.setattr("routers.admin.fingerprint_urls", fake_fingerprint_urls)
    engine, session_factory = _test_session_factory()
    asyncio.run(_seed_answer_keys(session_factory))
    app.dependency_overrides[get_session] = _override_session(session_factory)
    try:
        with TestClient(app, follow_redirects=False) as client:
            single = client.post(
                "/admin/option-key",
                auth=("admin", "change-me"),
                content=urlencode(
                    [
                        ("paper", "1"),
                        ("question_id", "q1"),
                        ("selected_image_url", "https://example.test/a.png"),
                        ("selected_image_url", "https://example.test/c.png"),
                    ]
                ),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            multiple = client.post(
                "/admin/option-key",
                auth=("admin", "change-me"),
                content=urlencode(
                    [
                        ("paper", "1"),
                        ("question_id", "q2"),
                        ("selected_image_url", "https://example.test/a.png"),
                        ("selected_image_url", "https://example.test/c.png"),
                    ]
                ),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        assert single.status_code == 200
        assert multiple.status_code == 200
        assert single.json()["count"] == 2
        assert multiple.json()["count"] == 2
        q1, q2 = asyncio.run(_load_keys(session_factory))
        assert q1.correct_option_hash_md5 == ["md5-a", "md5-c"]
        assert q1.correct_answer == {"mode": "image_hash", "count": 2}
        assert q2.correct_option_hash_md5 == ["md5-a", "md5-c"]
        assert q2.correct_option_hash_phash == ["0000000000000000", "00000000000000ff"]
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def _test_session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    asyncio.run(_create_schema(engine))
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _create_schema(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _override_session(session_factory):
    async def override():
        async with session_factory() as session:
            yield session

    return override


async def _seed_answer_keys(session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                AnswerKey(
                    paper=1,
                    subject="Physics",
                    section="Phy Sec 1",
                    question_id="q1",
                    answer_type="single",
                    correct_answer="A",
                ),
                AnswerKey(
                    paper=1,
                    subject="Physics",
                    section="Phy Sec 1",
                    question_id="q2",
                    answer_type="multiple",
                    correct_answer=["A", "C"],
                ),
            ]
        )
        await session.commit()


async def _load_keys(session_factory):
    async with session_factory() as session:
        keys = (
            await session.scalars(select(AnswerKey).where(AnswerKey.question_id.in_(["q1", "q2"])).order_by(AnswerKey.question_id))
        ).all()
        return keys
