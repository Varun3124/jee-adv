from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class AnswerKey(Base):
    __tablename__ = "answer_keys"
    __table_args__ = (UniqueConstraint("paper", "question_id", name="uq_answer_paper_question"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    paper: Mapped[int] = mapped_column(Integer, index=True)
    subject: Mapped[str] = mapped_column(String(32), index=True)
    section: Mapped[str] = mapped_column(String(80), default="")
    question_id: Mapped[str] = mapped_column(String(64), index=True)
    answer_type: Mapped[str] = mapped_column(String(24), default="single")
    correct_answer: Mapped[object] = mapped_column(JSON)
    correct_option_hash_md5: Mapped[object | None] = mapped_column(JSON, nullable=True)
    correct_option_hash_phash: Mapped[object | None] = mapped_column(JSON, nullable=True)
    full_marks: Mapped[float] = mapped_column(Float, default=4)
    partial_marks: Mapped[float] = mapped_column(Float, default=0)
    negative_marks: Mapped[float] = mapped_column(Float, default=0)
    rule_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    solution_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    solution_image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ResponseSheet(Base):
    __tablename__ = "response_sheets"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    submission_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_submission_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paper1_url: Mapped[str] = mapped_column(Text)
    paper2_url: Mapped[str] = mapped_column(Text)
    candidate_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    candidate_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    raw_parsed: Mapped[dict] = mapped_column(JSON)
    paper_scores: Mapped[dict] = mapped_column(JSON)
    section_scores: Mapped[dict] = mapped_column(JSON)
    total_score: Mapped[float] = mapped_column(Float, index=True)
    max_score: Mapped[float] = mapped_column(Float, default=0)
    estimated_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pool_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    percentile: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_candidates: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    questions: Mapped[list["QuestionResponse"]] = relationship(
        back_populates="response_sheet", cascade="all, delete-orphan"
    )


class QuestionResponse(Base):
    __tablename__ = "question_responses"
    __table_args__ = (UniqueConstraint("response_sheet_id", "paper", "question_id", name="uq_response_question"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    response_sheet_id: Mapped[int] = mapped_column(ForeignKey("response_sheets.id", ondelete="CASCADE"))
    paper: Mapped[int] = mapped_column(Integer, index=True)
    subject: Mapped[str] = mapped_column(String(32), index=True)
    section: Mapped[str] = mapped_column(String(80))
    question_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), default="")
    student_response: Mapped[object | None] = mapped_column(JSON, nullable=True)
    correct_answer: Mapped[object | None] = mapped_column(JSON, nullable=True)
    result: Mapped[str] = mapped_column(String(24), index=True)
    marks_awarded: Mapped[float] = mapped_column(Float, default=0)
    max_marks: Mapped[float] = mapped_column(Float, default=0)
    response_sheet: Mapped[ResponseSheet] = relationship(back_populates="questions")


class JoSAAClosingRank(Base):
    __tablename__ = "josaa_closing_ranks"

    id: Mapped[int] = mapped_column(primary_key=True)
    institute: Mapped[str] = mapped_column(String(255), index=True)
    program: Mapped[str] = mapped_column(String(255), index=True)
    quota: Mapped[str | None] = mapped_column(String(40), nullable=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    gender: Mapped[str] = mapped_column(String(80), index=True)
    round: Mapped[str] = mapped_column(String(40), index=True)
    opening_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    closing_rank: Mapped[int] = mapped_column(Integer, index=True)


class AppConfig(Base):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
