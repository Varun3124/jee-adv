import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import Base
from models import ResponseSheet
from services.rank import predict_rank_band, rank_for_score, set_config


@pytest.mark.parametrize(
    ("score", "expected_rank", "expected_label"),
    [
        (320, 20, "Under 20"),
        (280, 100, "Under 100"),
        (210, 300, "Under 300"),
    ],
)
def test_rank_prediction_uses_high_score_bands(score, expected_rank, expected_label):
    band = predict_rank_band(score, 999)
    assert band["estimated_rank"] == expected_rank
    assert band["estimated_rank_label"] == expected_label


@pytest.mark.asyncio
async def test_rank_estimation_counts_higher_scores_and_extrapolates_below_200():
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
        result = await rank_for_score(session, 150)

    await engine.dispose()
    assert result["pool_rank"] == 4
    assert result["estimated_rank"] == 1000
    assert result["estimated_rank_label"] == "Approx. 1000"
    assert result["percentile"] == 25.0


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
