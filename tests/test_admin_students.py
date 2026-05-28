import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database import Base, get_session
from main import app
from models import AnswerKey, QuestionResponse, ResponseSheet
from schemas import ParsedPaper, ParsedQuestion
from services.rank import rank_for_score, score_distribution, question_difficulty_map


@pytest.fixture
def engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    asyncio.run(_create_schema(engine))
    yield engine
    asyncio.run(engine.dispose())


@pytest.fixture
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def client(session_factory):
    app.dependency_overrides[get_session] = _override_session(session_factory)
    with TestClient(app, follow_redirects=False) as client:
        yield client
    app.dependency_overrides.clear()


async def _create_schema(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _override_session(session_factory):
    async def override():
        async with session_factory() as session:
            yield session

    return override


async def _seed_data(session_factory):
    async with session_factory() as session:
        now = datetime.utcnow()
        s1 = ResponseSheet(
            session_id="session1",
            submission_hash="hash1",
            paper1_url="url1",
            paper2_url="url2",
            candidate_id="ROLL01",
            candidate_name="Alice",
            raw_parsed={},
            paper_scores={"1": 100, "2": 150},
            section_scores={},
            total_score=250.0,
            max_score=360,
            created_at=now - timedelta(days=2),
            is_deleted=False,
        )
        s2 = ResponseSheet(
            session_id="session2",
            submission_hash="hash2",
            paper1_url="url3",
            paper2_url="url4",
            candidate_id="ROLL02",
            candidate_name="Bob",
            raw_parsed={},
            paper_scores={"1": 50, "2": 50},
            section_scores={},
            total_score=100.0,
            max_score=360,
            created_at=now - timedelta(days=1),
            is_deleted=False,
        )
        s3 = ResponseSheet(
            session_id="session3",
            submission_hash=None,
            deleted_submission_hash="hash3",
            paper1_url="url5",
            paper2_url="url6",
            candidate_id="ROLL03",
            candidate_name="Charlie",
            raw_parsed={},
            paper_scores={"1": 80, "2": 80},
            section_scores={},
            total_score=160.0,
            max_score=360,
            created_at=now,
            is_deleted=True,
            deleted_at=now,
        )
        session.add_all([s1, s2, s3])
        await session.commit()
        
        q1 = QuestionResponse(response_sheet_id=s1.id, paper=1, subject="Physics", section="Sec1", question_id="q1", result="correct")
        q2 = QuestionResponse(response_sheet_id=s2.id, paper=1, subject="Physics", section="Sec1", question_id="q1", result="incorrect")
        q3 = QuestionResponse(response_sheet_id=s3.id, paper=1, subject="Physics", section="Sec1", question_id="q1", result="correct")
        session.add_all([q1, q2, q3])
        await session.commit()
        return s1.id, s2.id, s3.id


def test_student_list_requires_auth(client):
    response = client.get("/admin/students")
    assert response.status_code == 401


def test_student_list_pagination_and_filters(client, session_factory):
    asyncio.run(_seed_data(session_factory))
    
    # Default shows only active (Alice, Bob)
    response = client.get("/admin/students", auth=("admin", "change-me"))
    assert response.status_code == 200
    assert "Alice" in response.text
    assert "Bob" in response.text
    assert "Charlie" not in response.text
    
    # Filter by name
    response = client.get("/admin/students?name=Ali", auth=("admin", "change-me"))
    assert "Alice" in response.text
    assert "Bob" not in response.text
    
    # Filter by roll
    response = client.get("/admin/students?roll=02", auth=("admin", "change-me"))
    assert "Bob" in response.text
    assert "Alice" not in response.text

    # Include deleted
    response = client.get("/admin/students?include_deleted=on", auth=("admin", "change-me"))
    assert "Alice" in response.text
    assert "Bob" in response.text
    assert "Charlie" in response.text


def test_admin_student_questions_view(client, session_factory):
    s1_id, _, s3_id = asyncio.run(_seed_data(session_factory))
    
    # Active entry
    response = client.get(f"/admin/students/{s1_id}/questions", auth=("admin", "change-me"))
    assert response.status_code == 200
    assert "Alice" in response.text
    assert "This entry has been soft-deleted" not in response.text
    
    # Deleted entry
    response = client.get(f"/admin/students/{s3_id}/questions", auth=("admin", "change-me"))
    assert response.status_code == 200
    assert "Charlie" in response.text
    assert "This entry has been soft-deleted" in response.text


def test_admin_recheck_updates_entry_against_current_answer_keys(client, session_factory):
    sheet_id = asyncio.run(_seed_recheck_data(session_factory))

    response = client.post(f"/admin/students/{sheet_id}/recheck", auth=("admin", "change-me"))
    assert response.status_code == 303

    async def load_state():
        async with session_factory() as session:
            sheet = await session.get(ResponseSheet, sheet_id)
            questions = (
                await session.scalars(
                    select(QuestionResponse).where(QuestionResponse.response_sheet_id == sheet_id)
                )
            ).all()
            key = await session.scalar(select(AnswerKey).where(AnswerKey.paper == 1, AnswerKey.question_id == "q1"))
            return sheet, questions, key

    sheet, questions, key = asyncio.run(load_state())
    assert key.correct_answer == "B"
    assert sheet.total_score == -1.0
    assert sheet.paper_scores == {"paper_1": -1.0}
    assert sheet.pool_rank == 1
    assert len(questions) == 1
    assert questions[0].result == "incorrect"
    assert questions[0].marks_awarded == -1.0


def test_single_delete_and_restore(client, session_factory):
    s1_id, _, _ = asyncio.run(_seed_data(session_factory))
    
    # Delete
    response = client.post(f"/admin/students/{s1_id}/delete", auth=("admin", "change-me"))
    assert response.status_code == 303
    
    async def get_sheet(sid):
        async with session_factory() as session:
            return await session.get(ResponseSheet, sid)
            
    s1 = asyncio.run(get_sheet(s1_id))
    assert s1.is_deleted is True
    assert s1.deleted_at is not None
    assert s1.submission_hash is None
    assert s1.deleted_submission_hash == "hash1"
    
    # Restore
    response = client.post(f"/admin/students/{s1_id}/restore", auth=("admin", "change-me"))
    assert response.status_code == 303
    
    s1 = asyncio.run(get_sheet(s1_id))
    assert s1.is_deleted is False
    assert s1.deleted_at is None
    assert s1.submission_hash == "hash1"
    assert s1.deleted_submission_hash is None


def test_bulk_delete(client, session_factory):
    s1_id, s2_id, _ = asyncio.run(_seed_data(session_factory))
    
    response = client.post(
        "/admin/students/bulk-delete",
        auth=("admin", "change-me"),
        data={"ids": [s1_id, s2_id]},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 303
    
    async def get_sheets(ids):
        async with session_factory() as session:
            return (await session.scalars(select(ResponseSheet).where(ResponseSheet.id.in_(ids)))).all()
            
    sheets = asyncio.run(get_sheets([s1_id, s2_id]))
    for s in sheets:
        assert s.is_deleted is True
        assert s.submission_hash is None


def test_restore_conflict_prevents_restore(client, session_factory):
    s1_id, s2_id, s3_id = asyncio.run(_seed_data(session_factory))
    
    async def create_conflict():
        async with session_factory() as session:
            s4 = ResponseSheet(
                session_id="session4",
                submission_hash="hash3", # Matches Charlie's deleted hash
                paper1_url="url7",
                paper2_url="url8",
                candidate_id="ROLL04",
                raw_parsed={},
                paper_scores={},
                section_scores={},
                total_score=0.0,
                max_score=360,
                is_deleted=False,
            )
            session.add(s4)
            await session.commit()
    
    asyncio.run(create_conflict())
    
    response = client.post(f"/admin/students/{s3_id}/restore", auth=("admin", "change-me"))
    assert response.status_code == 303
    # Check redirect URL contains error
    assert "error=" in response.headers["location"]
    
    async def get_sheet(sid):
        async with session_factory() as session:
            return await session.get(ResponseSheet, sid)
            
    s3 = asyncio.run(get_sheet(s3_id))
    assert s3.is_deleted is True # Not restored


@pytest.mark.asyncio
async def test_stats_exclude_deleted(session_factory):
    await _seed_data(session_factory)
    async with session_factory() as session:
        # Charlie (deleted) has score 160. Alice (active) has 250, Bob (active) has 100.
        
        # rank_for_score: pool_size should be 2, not 3
        rank_data = await rank_for_score(session, 150)
        assert rank_data["pool_size"] == 2
        
        # score_distribution: Should not include 160
        dist = await score_distribution(session)
        scores_in_dist = [d["start"] for d in dist]
        # Charlie's score shouldn't affect buckets
        # Just verifying it only processed 2 items implicitly via the previous test
        
        # question_difficulty_map
        # q1 for Alice (correct), Bob (incorrect), Charlie (correct, but deleted)
        # So total = 2, correct = 1 -> 50%
        diffs = await question_difficulty_map(session)
        assert diffs.get((1, "q1")) == 50.0


def test_public_routes_exclude_deleted(client, session_factory):
    asyncio.run(_seed_data(session_factory))
    
    # Active entry is visible
    response = client.get("/analysis/session1")
    assert response.status_code == 200
    
    response = client.get("/api/analysis/session1/section-breakdown")
    assert response.status_code == 200
    
    # Deleted entry returns 404
    response = client.get("/analysis/session3")
    assert response.status_code == 404
    
    response = client.get("/api/analysis/session3/section-breakdown")
    assert response.status_code == 404


async def _seed_recheck_data(session_factory):
    async with session_factory() as session:
        sheet = ResponseSheet(
            session_id="session-recheck",
            submission_hash="hash-recheck",
            paper1_url="url1",
            paper2_url="url2",
            candidate_id="ROLL99",
            candidate_name="Recheck",
            raw_parsed={
                "papers": [
                    ParsedPaper(
                        paper=1,
                        candidate_id="ROLL99",
                        candidate_name="Recheck",
                        source_url="url1",
                        questions=[
                            ParsedQuestion(
                                paper=1,
                                subject="Physics",
                                section="Sec1",
                                question_id="q1",
                                status="Answered",
                                response="A",
                            )
                        ],
                    ).model_dump()
                ]
            },
            paper_scores={"paper_1": 4.0},
            section_scores={
                "paper_1:Physics:Sec1": {
                    "paper": 1,
                    "subject": "Physics",
                    "section": "Sec1",
                    "score": 4.0,
                    "max_score": 4.0,
                    "attempted": 1,
                    "unattempted": 0,
                    "correct": 1,
                    "partial": 0,
                    "incorrect": 0,
                    "manual_review": 0,
                    "missing_key": 0,
                }
            },
            total_score=4.0,
            max_score=4.0,
            created_at=datetime.utcnow(),
            is_deleted=False,
        )
        session.add(sheet)
        session.add(
            AnswerKey(
                paper=1,
                subject="Physics",
                section="Sec1",
                question_id="q1",
                answer_type="single",
                correct_answer="A",
                full_marks=4,
                partial_marks=0,
                negative_marks=-1,
            )
        )
        await session.commit()
        session.add(
            QuestionResponse(
                response_sheet_id=sheet.id,
                paper=1,
                subject="Physics",
                section="Sec1",
                question_id="q1",
                status="Answered",
                student_response="A",
                correct_answer="A",
                result="correct",
                marks_awarded=4,
                max_marks=4,
            )
        )
        await session.commit()

        key = await session.scalar(select(AnswerKey).where(AnswerKey.paper == 1, AnswerKey.question_id == "q1"))
        key.correct_answer = "B"
        await session.commit()
        return sheet.id
