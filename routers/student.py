from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_session
from models import AnswerKey, QuestionResponse, ResponseSheet
from services.rank import question_difficulty_map
from services.submissions import create_submission_from_urls


router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/")
async def home(request: Request):
    return templates.TemplateResponse(request, "home.html")


@router.post("/submit")
async def submit(
    request: Request,
    paper1_url: str = Form(...),
    paper2_url: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    try:
        sheet = await create_submission_from_urls(session, paper1_url.strip(), paper2_url.strip())
    except Exception as exc:
        await session.rollback()
        return templates.TemplateResponse(
            request,
            "home.html",
            {"error": f"Could not process response sheets: {exc}"},
            status_code=400,
        )
    return RedirectResponse(f"/analysis/{sheet.session_id}", status_code=303)


@router.get("/analysis/{session_id}")
async def analysis(session_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    sheet = await _get_sheet(session, session_id)
    sections = sorted(sheet.section_scores.values(), key=lambda item: (item["paper"], item["subject"], item["section"]))
    return templates.TemplateResponse(request, "analysis.html", {"sheet": sheet, "sections": sections})


@router.get("/analysis/{session_id}/questions")
async def questions(session_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    sheet = await _get_sheet_with_questions(session, session_id)
    difficulties = await question_difficulty_map(session)
    keys = {
        (key.paper, key.question_id): key
        for key in (await session.scalars(select(AnswerKey))).all()
    }
    rows = []
    for question in sorted(sheet.questions, key=lambda q: (q.paper, q.subject, q.section, q.id)):
        key = keys.get((question.paper, question.question_id))
        rows.append(
            {
                "question": question,
                "difficulty": difficulties.get((question.paper, question.question_id), 0),
                "correct_answer_display": _correct_answer_display(question),
                "solution_text": key.solution_text if key else None,
                "solution_image_url": key.solution_image_url if key else None,
            }
        )
    return templates.TemplateResponse(request, "questions.html", {"sheet": sheet, "rows": rows})


@router.get("/analysis/{session_id}/rank")
async def rank_page(session_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    sheet = await _get_sheet(session, session_id)
    return templates.TemplateResponse(request, "rank.html", {"sheet": sheet})


async def _get_sheet(session: AsyncSession, session_id: str) -> ResponseSheet:
    sheet = await session.scalar(
        select(ResponseSheet).where(ResponseSheet.session_id == session_id, ResponseSheet.is_deleted == False)  # noqa: E712
    )
    if not sheet:
        raise HTTPException(status_code=404, detail="Analysis session not found")
    return sheet


def _correct_answer_display(question: QuestionResponse) -> object:
    if question.result == "manual_review":
        return "Pending manual review"
    if isinstance(question.correct_answer, dict) and question.correct_answer.get("mode") == "image_hash":
        return "Image-based key"
    return question.correct_answer if question.correct_answer is not None else "Missing key"


async def _get_sheet_with_questions(session: AsyncSession, session_id: str) -> ResponseSheet:
    sheet = await session.scalar(
        select(ResponseSheet)
        .options(selectinload(ResponseSheet.questions))
        .where(ResponseSheet.session_id == session_id, ResponseSheet.is_deleted == False)  # noqa: E712
    )
    if not sheet:
        raise HTTPException(status_code=404, detail="Analysis session not found")
    return sheet
