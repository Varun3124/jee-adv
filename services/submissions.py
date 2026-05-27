from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AnswerKey, QuestionResponse, ResponseSheet
from schemas import EvaluationResult, ParsedPaper, ParsedQuestion
from services.evaluator import evaluate_submission
from services.parser import fetch_response_sheet, parse_response_sheet
from services.rank import rank_for_score


async def create_submission_from_urls(session: AsyncSession, paper1_url: str, paper2_url: str) -> ResponseSheet:
    paper1 = _deduplicate_questions(parse_response_sheet(await fetch_response_sheet(paper1_url), paper1_url, 1))
    paper2 = _deduplicate_questions(parse_response_sheet(await fetch_response_sheet(paper2_url), paper2_url, 2))
    return await persist_submission(session, [paper1, paper2], paper1_url, paper2_url)


async def persist_submission(
    session: AsyncSession,
    papers: list[ParsedPaper],
    paper1_url: str,
    paper2_url: str,
) -> ResponseSheet:
    papers = [_deduplicate_questions(paper) for paper in papers]
    submission_hash = hash_submission(papers)
    existing = await session.scalar(select(ResponseSheet).where(ResponseSheet.submission_hash == submission_hash))
    if existing:
        return existing

    keys = {
        (key.paper, key.question_id): key
        for key in (await session.scalars(select(AnswerKey))).all()
    }
    evaluated = await evaluate_submission(papers, keys)
    parsed_json = [paper.model_dump() for paper in papers]
    candidate_id = next((paper.candidate_id for paper in papers if paper.candidate_id), None)
    candidate_name = next((paper.candidate_name for paper in papers if paper.candidate_name), None)
    sheet = ResponseSheet(
        session_id=uuid.uuid4().hex[:16],
        submission_hash=submission_hash,
        paper1_url=paper1_url,
        paper2_url=paper2_url,
        candidate_id=candidate_id,
        candidate_name=candidate_name,
        raw_parsed={"papers": parsed_json},
        paper_scores=evaluated.paper_scores,
        section_scores=evaluated.section_scores,
        total_score=evaluated.total_score,
        max_score=evaluated.max_score,
        estimated_rank=None,
        pool_rank=None,
        percentile=None,
        total_candidates=0,
    )
    session.add(sheet)
    await session.flush()
    ranks = await rank_for_score(session, evaluated.total_score)
    sheet.estimated_rank = int(ranks["estimated_rank"])
    sheet.pool_rank = int(ranks["pool_rank"])
    sheet.percentile = float(ranks["percentile"])
    sheet.total_candidates = int(ranks["total_candidates"])
    question_results = _deduplicate_question_results(evaluated.question_results)
    session.add_all(
        QuestionResponse(
            response_sheet_id=sheet.id,
            paper=result.paper,
            subject=result.subject,
            section=result.section,
            question_id=result.question_id,
            status=result.status,
            student_response=result.student_response,
            correct_answer=result.correct_answer,
            result=result.result,
            marks_awarded=result.marks_awarded,
            max_marks=result.max_marks,
        )
        for result in question_results
    )
    await session.commit()
    await session.refresh(sheet)
    return sheet


def hash_submission(papers: list[ParsedPaper]) -> str:
    papers = [_deduplicate_questions(paper) for paper in papers]
    pairs = []
    for paper in papers:
        for question in paper.questions:
            pairs.append((paper.paper, question.question_id, question.response))
    payload = json.dumps(sorted(pairs, key=lambda item: (item[0], item[1])), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _deduplicate_questions(paper: ParsedPaper) -> ParsedPaper:
    deduped: list[ParsedQuestion] = []
    question_index: dict[str, int] = {}
    for question in paper.questions:
        index = question_index.get(question.question_id)
        if index is None:
            question_index[question.question_id] = len(deduped)
            deduped.append(question)
            continue
        current = deduped[index]
        if _question_quality(question) > _question_quality(current):
            deduped[index] = question
    return paper.model_copy(update={"questions": deduped})


def _question_quality(question: ParsedQuestion) -> tuple[int, int, int, int, int]:
    status = (question.status or "").strip().lower()
    attempted = int(bool(question.response) and status not in {"not answered", "not attempted", "unanswered", "not visited"})
    response_present = int(question.response not in (None, "", []))
    image_count = len(question.option_image_urls)
    status_length = len(question.status or "")
    type_length = len(question.question_type or "")
    return (attempted, response_present, image_count, status_length, type_length)


def _deduplicate_question_results(results: list[EvaluationResult]) -> list[EvaluationResult]:
    deduped: list[EvaluationResult] = []
    index_by_key: dict[tuple[int, str], int] = {}
    for result in results:
        key = (result.paper, result.question_id)
        existing_index = index_by_key.get(key)
        if existing_index is None:
            index_by_key[key] = len(deduped)
            deduped.append(result)
            continue
        current = deduped[existing_index]
        if _result_quality(result) > _result_quality(current):
            deduped[existing_index] = result
    return deduped


def _result_quality(result: EvaluationResult) -> tuple[int, int, float, int]:
    rank = {
        "correct": 6,
        "partial": 5,
        "manual_review": 4,
        "incorrect": 3,
        "unattempted": 2,
        "missing_key": 1,
    }.get(result.result, 0)
    response_present = int(result.student_response not in (None, "", []))
    status_length = len(result.status or "")
    return (rank, response_present, float(result.marks_awarded), status_length)
