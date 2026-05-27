import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import Base
from models import ResponseSheet
from services.rank import rank_for_score, set_config


@pytest.mark.asyncio
async def test_rank_estimation_counts_higher_scores_and_extrapolates():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        await set_config(session, "total_candidates", 1000)
        session.add_all(
            [
                sheet("a", 300),
                sheet("b", 250),
                sheet("c", 250),
                sheet("d", 100),
            ]
        )
        await session.commit()
        result = await rank_for_score(session, 250)

    await engine.dispose()
    assert result["pool_rank"] == 2
    assert result["estimated_rank"] == 500
    assert result["percentile"] == 75.0


def sheet(session_id: str, score: float) -> ResponseSheet:
    return ResponseSheet(
        session_id=session_id,
        submission_hash=session_id * 8,
        paper1_url="p1",
        paper2_url="p2",
        raw_parsed={},
        paper_scores={},
        section_scores={},
        total_score=score,
        max_score=360,
        total_candidates=1000,
    )
