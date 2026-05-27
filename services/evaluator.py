from __future__ import annotations

from collections import defaultdict

from models import AnswerKey
from schemas import EvaluatedSubmission, EvaluationResult, ParsedPaper, ParsedQuestion
from services.image_hash import fingerprint_urls, phash_distance


UNATTEMPTED_STATUSES = {"not answered", "not attempted", "unanswered", "not visited", ""}
PHASH_DISTANCE_THRESHOLD = 8


async def evaluate_submission(
    papers: list[ParsedPaper], answer_keys: dict[tuple[int, str], AnswerKey]
) -> EvaluatedSubmission:
    question_results: list[EvaluationResult] = []
    paper_scores: dict[str, float] = defaultdict(float)
    section_scores: dict[str, dict[str, float | int]] = {}

    for paper in papers:
        for question in paper.questions:
            key = answer_keys.get((question.paper, question.question_id))
            result = await evaluate_question(question, key)
            question_results.append(result)
            paper_scores[f"paper_{question.paper}"] += result.marks_awarded
            section_key = f"paper_{question.paper}:{question.subject}:{question.section}"
            bucket = section_scores.setdefault(
                section_key,
                {
                    "paper": question.paper,
                    "subject": question.subject,
                    "section": question.section,
                    "score": 0.0,
                    "max_score": 0.0,
                    "attempted": 0,
                    "unattempted": 0,
                    "correct": 0,
                    "partial": 0,
                    "incorrect": 0,
                    "manual_review": 0,
                    "missing_key": 0,
                },
            )
            bucket["score"] = float(bucket["score"]) + result.marks_awarded
            bucket["max_score"] = float(bucket["max_score"]) + result.max_marks
            if result.result == "unattempted":
                bucket["unattempted"] = int(bucket["unattempted"]) + 1
            elif result.result == "missing_key":
                bucket["missing_key"] = int(bucket["missing_key"]) + 1
            else:
                bucket["attempted"] = int(bucket["attempted"]) + 1
                if result.result in {"correct", "partial", "incorrect", "manual_review"}:
                    bucket[result.result] = int(bucket[result.result]) + 1

    total_score = round(sum(paper_scores.values()), 2)
    max_score = round(sum(result.max_marks for result in question_results), 2)
    rounded_papers = {paper: round(score, 2) for paper, score in paper_scores.items()}
    rounded_sections = {
        key: {**value, "score": round(float(value["score"]), 2), "max_score": round(float(value["max_score"]), 2)}
        for key, value in section_scores.items()
    }
    return EvaluatedSubmission(
        paper_scores=rounded_papers,
        section_scores=rounded_sections,
        total_score=total_score,
        max_score=max_score,
        question_results=question_results,
    )


async def evaluate_question(question: ParsedQuestion, key: AnswerKey | None) -> EvaluationResult:
    if key is None and is_unattempted(question):
        return EvaluationResult(
            paper=question.paper,
            subject=question.subject,
            section=question.section,
            question_id=question.question_id,
            status=question.status,
            student_response=question.response,
            result="unattempted",
            marks_awarded=0,
            max_marks=0,
        )
    if key is None:
        return EvaluationResult(
            paper=question.paper,
            subject=question.subject,
            section=question.section,
            question_id=question.question_id,
            status=question.status,
            student_response=question.response,
            result="missing_key",
            marks_awarded=0,
            max_marks=0,
        )

    if is_unattempted(question):
        return _result(question, key, "unattempted", 0)

    correct = key.correct_answer
    answer_type = (key.answer_type or "single").lower()
    if _has_image_hashes(key) and answer_type in {"single", "multiple", "multi", "set"}:
        resolved = await _resolve_image_correct_answer(question, key)
        if resolved is None:
            return _manual_review_result(question, key)
        correct = resolved

    if answer_type == "numeric":
        outcome, marks = _score_numeric(question.response, correct, key)
    elif answer_type == "text":
        outcome, marks = _score_text(question.response, correct, key)
    elif answer_type in {"multiple", "multi", "set"}:
        outcome, marks = _score_multiple(question.response, correct, key)
    else:
        outcome, marks = _score_single(question.response, correct, key)
    return _result(question, key, outcome, marks)


def is_unattempted(question: ParsedQuestion) -> bool:
    return question.response in (None, "", []) or question.status.strip().lower() in UNATTEMPTED_STATUSES


def _score_single(response: object, correct: object, key: AnswerKey) -> tuple[str, float]:
    selected = _normalize_scalar(response)
    acceptable = _normalize_set(correct)
    if selected in acceptable:
        return "correct", key.full_marks
    return "incorrect", _negative(key)


def _score_text(response: object, correct: object, key: AnswerKey) -> tuple[str, float]:
    if str(response).strip().lower() == str(correct).strip().lower():
        return "correct", key.full_marks
    return "incorrect", _negative(key)


def _score_numeric(response: object, correct: object, key: AnswerKey) -> tuple[str, float]:
    rule_json = key.rule_json or {}
    try:
        value = float(str(response).strip())
    except (TypeError, ValueError):
        return "incorrect", _negative(key)
    if "min_value" in rule_json and "max_value" in rule_json:
        if float(rule_json["min_value"]) <= value <= float(rule_json["max_value"]):
            return "correct", key.full_marks
        return "incorrect", _negative(key)
    tolerance = float((key.rule_json or {}).get("tolerance", 0.01))
    try:
        if abs(value - float(str(correct).strip())) <= tolerance:
            return "correct", key.full_marks
    except (TypeError, ValueError):
        pass
    return "incorrect", _negative(key)


def _score_multiple(response: object, correct: object, key: AnswerKey) -> tuple[str, float]:
    selected = _normalize_set(response)
    correct_set = _normalize_set(correct)
    if selected == correct_set:
        return "correct", key.full_marks
    if not selected:
        return "unattempted", 0
    if not selected.issubset(correct_set):
        return "incorrect", _negative(key)
    correct_count = len(correct_set)
    selected_count = len(selected)
    if correct_count == 4 and selected_count == 3:
        return "partial", 3
    if correct_count >= 3 and selected_count == 2:
        return "partial", 2
    if correct_count >= 2 and selected_count == 1:
        return "partial", 1
    return "incorrect", _negative(key)


def _result(question: ParsedQuestion, key: AnswerKey, result: str, marks: float) -> EvaluationResult:
    return EvaluationResult(
        paper=question.paper,
        subject=question.subject,
        section=question.section,
        question_id=question.question_id,
        status=question.status,
        student_response=question.response,
        correct_answer=key.correct_answer,
        result=result,
        marks_awarded=round(float(marks), 2),
        max_marks=float(key.full_marks),
    )


def _manual_review_result(question: ParsedQuestion, key: AnswerKey) -> EvaluationResult:
    return EvaluationResult(
        paper=question.paper,
        subject=question.subject,
        section=question.section,
        question_id=question.question_id,
        status=question.status,
        student_response=question.response,
        correct_answer={"mode": "manual_review"},
        result="manual_review",
        marks_awarded=0,
        max_marks=float(key.full_marks),
    )


async def _resolve_image_correct_answer(question: ParsedQuestion, key: AnswerKey) -> str | list[str] | None:
    md5_hashes = _hash_list(key.correct_option_hash_md5)
    phashes = _hash_list(key.correct_option_hash_phash)
    if not md5_hashes or len(md5_hashes) != len(phashes):
        return None

    option_urls = {label.upper(): url for label, url in question.option_image_urls.items() if label.upper() in {"A", "B", "C", "D"}}
    if len(option_urls) < 4:
        return None

    try:
        by_url = await fingerprint_urls(list(option_urls.values()))
    except Exception:
        return None

    fingerprints = {label: by_url[url] for label, url in option_urls.items()}
    resolved_by_index: dict[int, str] = {}
    unresolved_indexes: list[int] = []

    for index, target_md5 in enumerate(md5_hashes):
        candidates = [label for label, fingerprint in fingerprints.items() if fingerprint.md5 == target_md5]
        if len(candidates) == 1:
            resolved_by_index[index] = candidates[0]
        elif len(candidates) > 1:
            return None
        else:
            unresolved_indexes.append(index)

    for index in unresolved_indexes:
        candidates = [
            label
            for label, fingerprint in fingerprints.items()
            if phash_distance(fingerprint.phash, phashes[index]) <= PHASH_DISTANCE_THRESHOLD
        ]
        if len(candidates) != 1:
            return None
        resolved_by_index[index] = candidates[0]

    resolved_labels = [resolved_by_index[index] for index in range(len(md5_hashes))]
    if len(set(resolved_labels)) != len(resolved_labels):
        return None
    if len(resolved_labels) == 1:
        return resolved_labels[0]
    return resolved_labels


def _has_image_hashes(key: AnswerKey) -> bool:
    return bool(key.correct_option_hash_md5 and key.correct_option_hash_phash)


def _hash_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _normalize_scalar(value: object) -> str:
    if isinstance(value, list):
        return ",".join(sorted(str(item).strip().upper() for item in value))
    return str(value).strip().upper()


def _normalize_set(value: object) -> set[str]:
    if isinstance(value, list):
        return {str(item).strip().upper() for item in value if str(item).strip()}
    if value is None:
        return set()
    text = str(value).upper().replace(" OR ", ",")
    for separator in (";", "/", "|", " "):
        text = text.replace(separator, ",")
    return {part.strip().upper() for part in text.split(",") if part.strip()}


def _negative(key: AnswerKey) -> float:
    if key.negative_marks == 0:
        return 0
    return key.negative_marks if key.negative_marks < 0 else -abs(key.negative_marks)
