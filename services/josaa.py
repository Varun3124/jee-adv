from __future__ import annotations

import csv
import io

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import JoSAAClosingRank


EXPECTED_COLUMNS = {
    "Institute",
    "Academic Program Name",
    "Quota",
    "Seat Type",
    "Gender",
    "Opening Rank",
    "Closing Rank",
}


def parse_josaa_csv(content: str) -> list[dict[str, object]]:
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames or not EXPECTED_COLUMNS.issubset(set(reader.fieldnames)):
        missing = sorted(EXPECTED_COLUMNS - set(reader.fieldnames or []))
        raise ValueError(f"Missing JoSAA CSV columns: {', '.join(missing)}")

    rows: list[dict[str, object]] = []
    for row in reader:
        closing_rank = _to_int(row.get("Closing Rank"))
        if closing_rank is None:
            continue
        rows.append(
            {
                "institute": (row.get("Institute") or "").strip(),
                "program": (row.get("Academic Program Name") or "").strip(),
                "quota": (row.get("Quota") or "").strip(),
                "category": (row.get("Seat Type") or "").strip().upper(),
                "gender": (row.get("Gender") or "").strip(),
                "round": (row.get("Round") or row.get("round") or "").strip() or "Unknown",
                "opening_rank": _to_int(row.get("Opening Rank")),
                "closing_rank": closing_rank,
            }
        )
    return rows


async def import_josaa_rows(session: AsyncSession, rows: list[dict[str, object]], replace: bool = False) -> int:
    if replace:
        await session.execute(delete(JoSAAClosingRank))
    session.add_all(JoSAAClosingRank(**row) for row in rows)
    return len(rows)


async def predict_colleges(
    session: AsyncSession,
    estimated_rank: int,
    category: str,
    gender: str,
    buffer_percent: int,
) -> list[JoSAAClosingRank]:
    buffered_rank = int(estimated_rank * (1 + buffer_percent / 100))
    stmt = (
        select(JoSAAClosingRank)
        .where(JoSAAClosingRank.category == category.upper())
        .where(JoSAAClosingRank.closing_rank >= buffered_rank)
        .order_by(JoSAAClosingRank.closing_rank.asc())
        .limit(200)
    )
    gender = gender.strip()
    if gender:
        stmt = stmt.where(JoSAAClosingRank.gender.ilike(f"%{gender}%"))
    return list((await session.scalars(stmt)).all())


def _to_int(value: object) -> int | None:
    text = str(value or "").replace(",", "").strip()
    if not text or text.upper() == "NA":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None
