import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import Base
from services.josaa import import_josaa_rows, parse_josaa_csv, predict_colleges


@pytest.mark.asyncio
async def test_josaa_import_and_prediction_filters():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    csv_text = """Institute,Academic Program Name,Quota,Seat Type,Gender,Opening Rank,Closing Rank,Round
IIT A,Computer Science,AI,OPEN,Gender-Neutral,1,1500,6
IIT B,Mechanical,AI,OPEN,Female-only (including Supernumerary),1000,5000,6
IIT C,Chemical,AI,SC,Gender-Neutral,100,9000,6
"""
    async with session_factory() as session:
        rows = parse_josaa_csv(csv_text)
        await import_josaa_rows(session, rows, replace=True)
        await session.commit()
        matches = await predict_colleges(session, estimated_rank=1200, category="OPEN", gender="Gender-Neutral", buffer_percent=10)

    await engine.dispose()
    assert len(matches) == 1
    assert matches[0].institute == "IIT A"
