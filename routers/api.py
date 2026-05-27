from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import get_settings
from database import get_session
from models import ResponseSheet
from services.josaa import predict_colleges
from services.rank import get_config_int, question_difficulty_map, score_distribution


router = APIRouter(prefix="/api")


@router.get("/analysis/{session_id}/section-breakdown")
async def section_breakdown(session_id: str, session: AsyncSession = Depends(get_session)):
    sheet = await _sheet(session, session_id)
    return {"sections": list(sheet.section_scores.values())}


@router.get("/analysis/{session_id}/score-distribution")
async def distribution(session_id: str, session: AsyncSession = Depends(get_session)):
    sheet = await _sheet(session, session_id)
    return {"student_score": sheet.total_score, "buckets": await score_distribution(session)}


@router.get("/questions/{session_id}")
async def question_data(session_id: str, session: AsyncSession = Depends(get_session)):
    sheet = await _sheet_with_questions(session, session_id)
    difficulties = await question_difficulty_map(session)
    return {
        "questions": [
            {
                "paper": q.paper,
                "subject": q.subject,
                "section": q.section,
                "question_id": q.question_id,
                "status": q.status,
                "student_response": q.student_response,
                "correct_answer": _correct_answer_display(q),
                "result": q.result,
                "marks_awarded": q.marks_awarded,
                "max_marks": q.max_marks,
                "difficulty": difficulties.get((q.paper, q.question_id), 0),
            }
            for q in sheet.questions
        ]
    }


@router.get("/josaa-predict/{session_id}")
async def josaa_predict(
    session_id: str,
    category: str = Query("OPEN"),
    gender: str = Query("Gender-Neutral"),
    session: AsyncSession = Depends(get_session),
):
    sheet = await _sheet(session, session_id)
    settings = get_settings()
    buffer_percent = await get_config_int(session, "rank_buffer_percent", settings.rank_buffer_percent)
    rows = await predict_colleges(session, int(sheet.estimated_rank or 0), category, gender, buffer_percent)
    return {
        "buffer_percent": buffer_percent,
        "results": [
            {
                "institute": row.institute,
                "program": row.program,
                "quota": row.quota,
                "category": row.category,
                "gender": row.gender,
                "round": row.round,
                "opening_rank": row.opening_rank,
                "closing_rank": row.closing_rank,
            }
            for row in rows
        ],
    }


async def _sheet(session: AsyncSession, session_id: str) -> ResponseSheet:
    sheet = await session.scalar(
        select(ResponseSheet).where(ResponseSheet.session_id == session_id, ResponseSheet.is_deleted == False)  # noqa: E712
    )
    if not sheet:
        raise HTTPException(status_code=404, detail="Analysis session not found")
    return sheet


def _correct_answer_display(question) -> object:
    if question.result == "manual_review":
        return "Pending manual review"
    if isinstance(question.correct_answer, dict) and question.correct_answer.get("mode") == "image_hash":
        return "Image-based key"
    return question.correct_answer


async def _sheet_with_questions(session: AsyncSession, session_id: str) -> ResponseSheet:
    sheet = await session.scalar(
        select(ResponseSheet)
        .options(selectinload(ResponseSheet.questions))
        .where(ResponseSheet.session_id == session_id, ResponseSheet.is_deleted == False)  # noqa: E712
    )
    if not sheet:
        raise HTTPException(status_code=404, detail="Analysis session not found")
    return sheet
