from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AnswerKey, QuestionResponse, ResponseSheet
from schemas import ParsedPaper
from services.evaluator import evaluate_submission
from services.parser import parse_response_sheet
from services.rank import rank_for_score


PDF_ANSWER_RE = re.compile(r"Answer\s+Q(\d+)\s*:\s*([^\n]+)")
DEFAULT_PDFS = {
    1: Path(r"C:\Users\varun\Downloads\p1_provisional_keys.pdf"),
    2: Path(r"C:\Users\varun\Downloads\p2_provisional_keys.pdf"),
}
FIXTURES = {
    1: Path("tests/fixtures/paper1_sample.html"),
    2: Path("tests/fixtures/paper2_sample.html"),
}


def extract_pdf_answers(pdf_path: Path) -> list[str]:
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)
    return [_clean_answer(answer) for _, answer in PDF_ANSWER_RE.findall(text)]


def build_answer_keys(pdf_paths: dict[int, Path] | None = None) -> list[AnswerKey]:
    pdf_paths = pdf_paths or DEFAULT_PDFS
    keys: list[AnswerKey] = []
    for paper in (1, 2):
        answers = extract_pdf_answers(pdf_paths[paper])
        expected = 48 if paper == 1 else 54
        if len(answers) != expected:
            raise ValueError(f"Paper {paper} expected {expected} answers, found {len(answers)}")
        qid_by_global = _question_ids_by_global_number(paper)
        for offset, answer in enumerate(answers, start=1):
            global_number = offset if paper == 1 else offset + 48
            keys.append(_make_answer_key(paper, global_number, qid_by_global[global_number], answer))
    return keys


async def import_pdf_answer_keys(session: AsyncSession, pdf_paths: dict[int, Path] | None = None) -> int:
    keys = build_answer_keys(pdf_paths)
    await session.execute(delete(AnswerKey).where(AnswerKey.paper.in_([1, 2])))
    session.add_all(keys)
    await session.flush()
    await refresh_existing_submissions(session)
    await session.commit()
    return len(keys)


async def refresh_existing_submissions(session: AsyncSession) -> int:
    answer_keys = {(key.paper, key.question_id): key for key in (await session.scalars(select(AnswerKey))).all()}
    sheets = (await session.scalars(select(ResponseSheet))).all()
    for sheet in sheets:
        papers = [ParsedPaper(**paper) for paper in sheet.raw_parsed.get("papers", [])]
        evaluated = await evaluate_submission(papers, answer_keys)
        await session.execute(delete(QuestionResponse).where(QuestionResponse.response_sheet_id == sheet.id))
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
            for result in evaluated.question_results
        )
        sheet.paper_scores = evaluated.paper_scores
        sheet.section_scores = evaluated.section_scores
        sheet.total_score = evaluated.total_score
        sheet.max_score = evaluated.max_score
        ranks = await rank_for_score(session, sheet.total_score)
        sheet.estimated_rank = int(ranks["estimated_rank"])
        sheet.pool_rank = int(ranks["pool_rank"])
        sheet.percentile = float(ranks["percentile"])
        sheet.total_candidates = int(ranks["total_candidates"])
    return len(sheets)


def _question_ids_by_global_number(paper: int) -> dict[int, str]:
    parsed = parse_response_sheet(FIXTURES[paper].read_text(encoding="utf-8"), str(FIXTURES[paper]), paper)
    mapping: dict[int, str] = {}
    for question in parsed.questions:
        suffix = int(question.question_id[6:])
        mapping[suffix] = question.question_id
    expected = set(range(1, 49)) if paper == 1 else set(range(49, 103))
    missing = sorted(expected - set(mapping))
    if missing:
        raise ValueError(f"Missing question IDs for paper {paper}: {missing}")
    return mapping


def _make_answer_key(paper: int, global_number: int, question_id: str, answer: str) -> AnswerKey:
    subject, section = _subject_section(paper, global_number)
    answer_type, full_marks, partial_marks, negative_marks, rule_json, correct_answer = _scheme(global_number, answer)
    return AnswerKey(
        paper=paper,
        subject=subject,
        section=section,
        question_id=question_id,
        answer_type=answer_type,
        correct_answer=correct_answer,
        full_marks=full_marks,
        partial_marks=partial_marks,
        negative_marks=negative_marks,
        rule_json=rule_json,
    )


def _subject_section(paper: int, global_number: int) -> tuple[str, str]:
    local = global_number if paper == 1 else global_number - 48
    per_subject = 16 if paper == 1 else 18
    subject_index = (local - 1) // per_subject
    within_subject = (local - 1) % per_subject + 1
    subject = ["Mathematics", "Physics", "Chemistry"][subject_index]
    if paper == 1:
        section_index = (within_subject - 1) // 4 + 1
    else:
        section_index = 1 if within_subject <= 4 else 2 if within_subject <= 9 else 3
    prefix = {"Mathematics": "Math", "Physics": "Phy", "Chemistry": "Chem"}[subject]
    return subject, f"{prefix} Sec {section_index}"


def _scheme(global_number: int, answer: str) -> tuple[str, float, float, float, dict | None, object]:
    if 1 <= global_number <= 48:
        within = (global_number - 1) % 16 + 1
        if 1 <= within <= 4:
            return "single", 3, 0, -1, None, answer
        if 5 <= within <= 8:
            return "multiple", 4, 0, -1, {"partial_scheme": "jee_advanced_2026"}, list(answer)
        if 9 <= within <= 12:
            return _numeric_scheme(answer, 4)
        return "single", 4, 0, -1, None, answer
    within = (global_number - 49) % 18 + 1
    if 1 <= within <= 4:
        return "single", 3, 0, -1, None, answer
    if 5 <= within <= 9:
        return "multiple", 4, 0, -1, {"partial_scheme": "jee_advanced_2026"}, list(answer)
    return _numeric_scheme(answer, 4)


def _numeric_scheme(answer: str, full_marks: float) -> tuple[str, float, float, float, dict, str]:
    numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", answer)]
    if not numbers:
        raise ValueError(f"Numeric answer has no number: {answer}")
    return "numeric", full_marks, 0, 0, {"min_value": min(numbers), "max_value": max(numbers)}, answer


def _clean_answer(answer: str) -> str:
    return re.sub(r"\s+", " ", answer).strip().strip("[]").upper().replace(" TO ", " to ")
