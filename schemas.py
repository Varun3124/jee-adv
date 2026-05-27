from __future__ import annotations

from pydantic import BaseModel, Field


class ParsedQuestion(BaseModel):
    paper: int
    subject: str
    section: str
    question_id: str
    question_type: str = ""
    status: str = ""
    response: str | list[str] | None = None
    option_image_urls: dict[str, str] = Field(default_factory=dict)


class ParsedPaper(BaseModel):
    paper: int
    candidate_id: str | None = None
    candidate_name: str | None = None
    source_url: str
    questions: list[ParsedQuestion] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    paper: int
    subject: str
    section: str
    question_id: str
    status: str
    student_response: object | None = None
    correct_answer: object | None = None
    result: str
    marks_awarded: float
    max_marks: float


class EvaluatedSubmission(BaseModel):
    paper_scores: dict[str, float]
    section_scores: dict[str, dict[str, object]]
    total_score: float
    max_score: float
    question_results: list[EvaluationResult]
