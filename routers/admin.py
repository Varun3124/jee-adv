from __future__ import annotations

import json
import math
import secrets
from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import get_settings
from database import AsyncSessionLocal, get_session
from models import AnswerKey, JoSAAClosingRank, QuestionResponse, ResponseSheet
from schemas import ParsedPaper
from services.image_hash import fingerprint_urls
from services.josaa import import_josaa_rows, parse_josaa_csv
from services.parser import fetch_response_sheet, parse_response_sheet
from services.rank import clear_pool, get_config_int, question_difficulty_map, set_config
from services.answer_key_importer import refresh_submission
from services.submissions import create_submission_from_urls


router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")
security = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    settings = get_settings()
    valid_username = secrets.compare_digest(credentials.username, settings.admin_username)
    valid_password = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (valid_username and valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@router.get("")
async def admin_home(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    answer_keys = (await session.scalars(select(AnswerKey).order_by(AnswerKey.paper, AnswerKey.subject, AnswerKey.id))).all()
    response_count = await session.scalar(select(func.count(ResponseSheet.id))) or 0
    active_student_count = (
        await session.scalar(
            select(func.count(ResponseSheet.id)).where(ResponseSheet.is_deleted == False)  # noqa: E712
        )
    ) or 0
    josaa_count = await session.scalar(select(func.count(JoSAAClosingRank.id))) or 0
    total_candidates = await get_config_int(session, "total_candidates", settings.total_candidates)
    rank_buffer_percent = await get_config_int(session, "rank_buffer_percent", settings.rank_buffer_percent)
    return templates.TemplateResponse(
        request,
        "admin/index.html",
        {
            "answer_keys": answer_keys,
            "response_count": response_count,
            "active_student_count": active_student_count,
            "josaa_count": josaa_count,
            "total_candidates": total_candidates,
            "rank_buffer_percent": rank_buffer_percent,
        },
    )


# ---------------------------------------------------------------------------
# Student Entries: list, view, delete, bulk-delete, restore
# ---------------------------------------------------------------------------

@router.get("/students")
async def student_list(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    roll: str = Query(""),
    name: str = Query(""),
    min_score: str = Query(""),
    max_score: str = Query(""),
    date_from: str = Query(""),
    date_to: str = Query(""),
    include_deleted: str = Query(""),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    error: str = Query(""),
    info: str = Query(""),
):
    query = select(ResponseSheet)
    count_query = select(func.count(ResponseSheet.id))

    # Filters
    if not include_deleted:
        query = query.where(ResponseSheet.is_deleted == False)  # noqa: E712
        count_query = count_query.where(ResponseSheet.is_deleted == False)  # noqa: E712

    if roll.strip():
        query = query.where(ResponseSheet.candidate_id.ilike(f"%{roll.strip()}%"))
        count_query = count_query.where(ResponseSheet.candidate_id.ilike(f"%{roll.strip()}%"))

    if name.strip():
        query = query.where(ResponseSheet.candidate_name.ilike(f"%{name.strip()}%"))
        count_query = count_query.where(ResponseSheet.candidate_name.ilike(f"%{name.strip()}%"))

    if min_score.strip():
        try:
            ms = float(min_score)
            query = query.where(ResponseSheet.total_score >= ms)
            count_query = count_query.where(ResponseSheet.total_score >= ms)
        except ValueError:
            pass

    if max_score.strip():
        try:
            ms = float(max_score)
            query = query.where(ResponseSheet.total_score <= ms)
            count_query = count_query.where(ResponseSheet.total_score <= ms)
        except ValueError:
            pass

    if date_from.strip():
        try:
            df = datetime.strptime(date_from.strip(), "%Y-%m-%d")
            query = query.where(ResponseSheet.created_at >= df)
            count_query = count_query.where(ResponseSheet.created_at >= df)
        except ValueError:
            pass

    if date_to.strip():
        try:
            dt = datetime.strptime(date_to.strip(), "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            query = query.where(ResponseSheet.created_at <= dt)
            count_query = count_query.where(ResponseSheet.created_at <= dt)
        except ValueError:
            pass

    total_count = await session.scalar(count_query) or 0
    total_pages = max(1, math.ceil(total_count / per_page))
    page = min(page, total_pages)

    students = (
        await session.scalars(
            query.order_by(ResponseSheet.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).all()

    # Counts for summary
    active_count = await session.scalar(
        select(func.count(ResponseSheet.id)).where(ResponseSheet.is_deleted == False)  # noqa: E712
    ) or 0
    deleted_count = await session.scalar(
        select(func.count(ResponseSheet.id)).where(ResponseSheet.is_deleted == True)  # noqa: E712
    ) or 0

    filters = {
        "roll": roll,
        "name": name,
        "min_score": min_score,
        "max_score": max_score,
        "date_from": date_from,
        "date_to": date_to,
        "include_deleted": include_deleted,
    }

    def pagination_qs(p: int) -> str:
        params = {k: v for k, v in filters.items() if v}
        params["page"] = str(p)
        params["per_page"] = str(per_page)
        return urlencode(params)

    return templates.TemplateResponse(
        request,
        "admin/students.html",
        {
            "students": students,
            "filters": filters,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "total_shown": total_count,
            "active_count": active_count,
            "deleted_count": deleted_count,
            "pagination_qs": pagination_qs,
            "error": error,
            "info": info,
        },
    )


@router.get("/students/{sheet_id}/questions")
async def admin_student_questions(
    sheet_id: int,
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    sheet = await session.scalar(
        select(ResponseSheet)
        .options(selectinload(ResponseSheet.questions))
        .where(ResponseSheet.id == sheet_id)
    )
    if not sheet:
        raise HTTPException(status_code=404, detail="Student entry not found")

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
    return templates.TemplateResponse(
        request, "admin/student_questions.html", {"sheet": sheet, "rows": rows}
    )


@router.post("/students/{sheet_id}/delete")
async def delete_student(
    sheet_id: int,
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    sheet = await session.get(ResponseSheet, sheet_id)
    if not sheet:
        raise HTTPException(status_code=404, detail="Student entry not found")
    if sheet.is_deleted:
        return _redirect_students(request, info="Entry is already deleted.")

    sheet.is_deleted = True
    sheet.deleted_at = datetime.utcnow()
    sheet.deleted_submission_hash = sheet.submission_hash
    sheet.submission_hash = None
    await session.commit()
    return _redirect_students(request, info="Entry deleted.")


@router.post("/students/bulk-delete")
async def bulk_delete_students(
    request: Request,
    ids: list[int] = Form(default=[]),
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if not ids:
        return _redirect_students(request, error="No entries selected.")

    sheets = (
        await session.scalars(
            select(ResponseSheet).where(
                ResponseSheet.id.in_(ids),
                ResponseSheet.is_deleted == False,  # noqa: E712
            )
        )
    ).all()
    now = datetime.utcnow()
    for sheet in sheets:
        sheet.is_deleted = True
        sheet.deleted_at = now
        sheet.deleted_submission_hash = sheet.submission_hash
        sheet.submission_hash = None
    await session.commit()
    return _redirect_students(request, info=f"{len(sheets)} entry/entries deleted.")


@router.post("/students/{sheet_id}/restore")
async def restore_student(
    sheet_id: int,
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    sheet = await session.get(ResponseSheet, sheet_id)
    if not sheet:
        raise HTTPException(status_code=404, detail="Student entry not found")
    if not sheet.is_deleted:
        return _redirect_students(request, info="Entry is already active.")

    if sheet.deleted_submission_hash:
        conflict = await session.scalar(
            select(ResponseSheet).where(
                ResponseSheet.submission_hash == sheet.deleted_submission_hash,
                ResponseSheet.is_deleted == False,  # noqa: E712
                ResponseSheet.id != sheet.id,
            )
        )
        if conflict:
            return _redirect_students(
                request,
                error=f"Cannot restore: another active entry already has this submission hash (ID {conflict.id}).",
            )

    sheet.submission_hash = sheet.deleted_submission_hash
    sheet.deleted_submission_hash = None
    sheet.deleted_at = None
    sheet.is_deleted = False
    await session.commit()
    return _redirect_students(request, info="Entry restored.")


@router.post("/students/{sheet_id}/recheck")
async def recheck_student(
    sheet_id: int,
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    sheet = await session.get(ResponseSheet, sheet_id)
    if not sheet:
        raise HTTPException(status_code=404, detail="Student entry not found")

    await refresh_submission(session, sheet_id)
    await session.commit()
    return _redirect_students(request, info="Entry re-checked against current answer keys.")


def _redirect_students(request: Request, error: str = "", info: str = "") -> RedirectResponse:
    """Redirect back to /admin/students preserving query filters."""
    params: dict[str, str] = {}
    for key in ("roll", "name", "min_score", "max_score", "date_from", "date_to", "include_deleted", "page", "per_page"):
        val = request.query_params.get(key, "")
        if not val:
            # Also check form data isn't available via query params for POST
            pass
        if val:
            params[key] = val
    if error:
        params["error"] = error
    if info:
        params["info"] = info
    qs = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"/admin/students{qs}", status_code=303)


def _correct_answer_display(question: QuestionResponse) -> object:
    if question.result == "manual_review":
        return "Pending manual review"
    if isinstance(question.correct_answer, dict) and question.correct_answer.get("mode") == "image_hash":
        return "Image-based key"
    return question.correct_answer if question.correct_answer is not None else "Missing key"


# ---------------------------------------------------------------------------
# Existing admin endpoints (answer keys, ingestion, JoSAA, config)
# ---------------------------------------------------------------------------

@router.post("/answer-key")
async def upsert_answer_key(
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    paper: int = Form(...),
    subject: str = Form(...),
    section: str = Form(""),
    question_id: str = Form(...),
    answer_type: str = Form("single"),
    correct_answer: str = Form(...),
    full_marks: float = Form(4),
    partial_marks: float = Form(0),
    negative_marks: float = Form(0),
    solution_text: str = Form(""),
    solution_image_url: str = Form(""),
):
    parsed_answer = _json_or_text(correct_answer)
    existing = await session.scalar(
        select(AnswerKey).where(AnswerKey.paper == paper, AnswerKey.question_id == question_id.strip())
    )
    data = {
        "paper": paper,
        "subject": subject,
        "section": section,
        "question_id": question_id.strip(),
        "answer_type": answer_type,
        "correct_answer": parsed_answer,
        "full_marks": full_marks,
        "partial_marks": partial_marks,
        "negative_marks": negative_marks,
        "solution_text": solution_text or None,
        "solution_image_url": solution_image_url or None,
    }
    if existing:
        for key, value in data.items():
            setattr(existing, key, value)
    else:
        session.add(AnswerKey(**data))
    await session.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/answer-key/import")
async def import_answer_key(
    file: UploadFile = File(...),
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    payload = json.loads((await file.read()).decode("utf-8"))
    rows = payload if isinstance(payload, list) else payload.get("items", [])
    for row in rows:
        row["correct_answer"] = _json_or_text(row.get("correct_answer"))
        session.add(AnswerKey(**row))
    await session.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/option-picker")
async def option_picker(
    request: Request,
    paper1_url: str = Form(...),
    paper2_url: str = Form(...),
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    papers = [
        parse_response_sheet(await fetch_response_sheet(paper1_url.strip()), paper1_url.strip(), 1),
        parse_response_sheet(await fetch_response_sheet(paper2_url.strip()), paper2_url.strip(), 2),
    ]
    keys = {
        (key.paper, key.question_id): key
        for key in (await session.scalars(select(AnswerKey).order_by(AnswerKey.paper, AnswerKey.id))).all()
    }
    rows = _picker_rows(papers, keys)
    return templates.TemplateResponse(
        request,
        "admin/option_picker.html",
        {
            "rows": rows,
            "paper1_url": paper1_url.strip(),
            "paper2_url": paper2_url.strip(),
        },
    )


@router.post("/option-key")
async def save_option_key(
    request: Request,
    paper: int = Form(...),
    question_id: str = Form(...),
    selected_image_url: list[str] = Form(...),
    paper1_url: str = Form(None),
    paper2_url: str = Form(None),
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    key = await session.scalar(select(AnswerKey).where(AnswerKey.paper == paper, AnswerKey.question_id == question_id.strip()))
    if key is None:
        raise HTTPException(status_code=404, detail="Answer key must exist before saving option image hashes.")

    answer_type = (key.answer_type or "single").lower()
    if answer_type in {"multiple", "multi", "set"} and not selected_image_url:
        raise HTTPException(status_code=400, detail="Multiple-correct questions must have at least one selected option image.")
    if answer_type == "single" and not selected_image_url:
        raise HTTPException(status_code=400, detail="Single-answer questions must have at least one selected option image.")
    if answer_type not in {"single", "multiple", "multi", "set"}:
        raise HTTPException(status_code=400, detail="Image option hashes can only be saved for MCQ/MSQ questions.")

    fingerprints = await fingerprint_urls(selected_image_url)
    md5_hashes = [fingerprints[url].md5 for url in selected_image_url]
    phashes = [fingerprints[url].phash for url in selected_image_url]
    key.correct_option_hash_md5 = md5_hashes[0] if len(md5_hashes) == 1 else md5_hashes
    key.correct_option_hash_phash = phashes[0] if len(phashes) == 1 else phashes
    key.correct_answer = {"mode": "image_hash", "count": len(md5_hashes)}
    await session.commit()
    return {"status": "ok", "paper": paper, "question_id": question_id, "count": len(md5_hashes)}


@router.post("/ingest")
async def ingest_responses(
    background_tasks: BackgroundTasks,
    urls: str = Form(...),
    _: str = Depends(require_admin),
):
    lines = [line.strip() for line in urls.splitlines() if line.strip()]
    for index in range(0, len(lines) - 1, 2):
        background_tasks.add_task(_ingest_pair, lines[index], lines[index + 1])
    return RedirectResponse("/admin", status_code=303)


@router.post("/josaa/import")
async def import_josaa(
    file: UploadFile = File(...),
    mode: str = Form("append"),
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    rows = parse_josaa_csv((await file.read()).decode("utf-8-sig"))
    await import_josaa_rows(session, rows, replace=(mode == "replace"))
    await session.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/config")
async def update_config(
    total_candidates: int = Form(...),
    rank_buffer_percent: int = Form(...),
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await set_config(session, "total_candidates", total_candidates)
    await set_config(session, "rank_buffer_percent", rank_buffer_percent)
    await session.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/reset-pool")
async def reset_pool(_: str = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    await clear_pool(session)
    await session.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/answer-key/clear")
async def clear_answer_key(_: str = Depends(require_admin), session: AsyncSession = Depends(get_session)):
    from sqlalchemy import delete
    await session.execute(delete(AnswerKey))
    await session.commit()
    return RedirectResponse("/admin", status_code=303)


async def _ingest_pair(paper1_url: str, paper2_url: str) -> None:
    async with AsyncSessionLocal() as session:
        try:
            await create_submission_from_urls(session, paper1_url, paper2_url)
        except Exception:
            await session.rollback()


def _json_or_text(value: object) -> object:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _picker_rows(papers: list[ParsedPaper], keys: dict[tuple[int, str], AnswerKey]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for paper in papers:
        for question in paper.questions:
            key = keys.get((question.paper, question.question_id))
            answer_type = (key.answer_type or "").lower() if key else ""
            if not key or answer_type not in {"single", "multiple", "multi", "set"} or not question.option_image_urls:
                continue
            rows.append(
                {
                    "question": question,
                    "key": key,
                    "is_multiple": True,
                    "is_hashed": bool(key.correct_option_hash_md5 and key.correct_option_hash_phash),
                }
            )
    return rows

