from __future__ import annotations

import math

from sqlalchemy import case, delete, func, join, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models import AppConfig, QuestionResponse, ResponseSheet


async def get_config_int(session: AsyncSession, key: str, default: int) -> int:
    row = await session.get(AppConfig, key)
    if row is None:
        return default
    try:
        return int(row.value)
    except ValueError:
        return default


async def set_config(session: AsyncSession, key: str, value: str | int) -> None:
    row = await session.get(AppConfig, key)
    if row is None:
        session.add(AppConfig(key=key, value=str(value)))
    else:
        row.value = str(value)


def predict_rank_band(score: float, fallback_rank: int | None = None) -> dict[str, int | str]:
    if score >= 300:
        return {"estimated_rank": 20, "estimated_rank_label": "Under 20"}
    if score >= 270:
        return {"estimated_rank": 100, "estimated_rank_label": "Under 100"}
    if score >= 200:
        return {"estimated_rank": 300, "estimated_rank_label": "Under 300"}

    estimated_rank = max(1, int(fallback_rank or 1))
    return {"estimated_rank": estimated_rank, "estimated_rank_label": f"Approx. {estimated_rank}"}


async def rank_for_score(session: AsyncSession, score: float) -> dict[str, int | float | str]:
    settings = get_settings()
    total_candidates = await get_config_int(session, "total_candidates", settings.total_candidates)
    active_filter = ResponseSheet.is_deleted == False  # noqa: E712
    pool_size = await session.scalar(select(func.count(ResponseSheet.id)).where(active_filter)) or 0
    higher = await session.scalar(select(func.count(ResponseSheet.id)).where(active_filter, ResponseSheet.total_score > score)) or 0
    lower_or_equal = await session.scalar(select(func.count(ResponseSheet.id)).where(active_filter, ResponseSheet.total_score <= score)) or 0
    pool_rank = int(higher) + 1
    percentile = round((float(lower_or_equal) / float(pool_size) * 100), 2) if pool_size else 100.0
    legacy_estimated_rank = math.ceil(pool_rank / max(int(pool_size), 1) * int(total_candidates))
    band = predict_rank_band(score, legacy_estimated_rank)
    return {
        "pool_size": int(pool_size),
        "pool_rank": pool_rank,
        "estimated_rank": max(1, int(band["estimated_rank"])),
        "estimated_rank_label": band["estimated_rank_label"],
        "percentile": percentile,
        "total_candidates": int(total_candidates),
    }


async def score_distribution(session: AsyncSession) -> list[dict[str, float | int]]:
    scores = [
        float(score)
        for score in (
            await session.scalars(
                select(ResponseSheet.total_score).where(ResponseSheet.is_deleted == False)  # noqa: E712
            )
        ).all()
    ]
    if not scores:
        return []
    minimum, maximum = math.floor(min(scores)), math.ceil(max(scores))
    bucket_count = min(20, max(5, len(set(scores))))
    width = max(1, math.ceil((maximum - minimum + 1) / bucket_count))
    buckets: dict[int, int] = {}
    for score in scores:
        start = minimum + math.floor((score - minimum) / width) * width
        buckets[start] = buckets.get(start, 0) + 1
    return [{"label": f"{start}-{start + width - 1}", "count": count, "start": start} for start, count in sorted(buckets.items())]


async def question_difficulty_map(session: AsyncSession) -> dict[tuple[int, str], float]:
    j = join(QuestionResponse, ResponseSheet, QuestionResponse.response_sheet_id == ResponseSheet.id)
    rows = (
        await session.execute(
            select(
                QuestionResponse.paper,
                QuestionResponse.question_id,
                func.count(QuestionResponse.id),
                func.sum(case((QuestionResponse.result == "correct", 1), else_=0)),
            )
            .select_from(j)
            .where(ResponseSheet.is_deleted == False)  # noqa: E712
            .group_by(QuestionResponse.paper, QuestionResponse.question_id)
        )
    ).all()
    return {
        (int(paper), str(question_id)): round((int(correct or 0) / int(total) * 100), 2) if total else 0.0
        for paper, question_id, total, correct in rows
    }


async def clear_pool(session: AsyncSession) -> None:
    await session.execute(delete(ResponseSheet))

