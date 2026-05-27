from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_answer_key_hash_columns)
        await conn.run_sync(_ensure_response_sheet_soft_delete_columns)


def _ensure_answer_key_hash_columns(sync_conn) -> None:
    inspector = inspect(sync_conn)
    if "answer_keys" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("answer_keys")}
    if "correct_option_hash_md5" not in columns:
        sync_conn.execute(text("ALTER TABLE answer_keys ADD COLUMN correct_option_hash_md5 JSON"))
    if "correct_option_hash_phash" not in columns:
        sync_conn.execute(text("ALTER TABLE answer_keys ADD COLUMN correct_option_hash_phash JSON"))


def _ensure_response_sheet_soft_delete_columns(sync_conn) -> None:
    inspector = inspect(sync_conn)
    if "response_sheets" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("response_sheets")}
    if "is_deleted" not in columns:
        sync_conn.execute(text("ALTER TABLE response_sheets ADD COLUMN is_deleted BOOLEAN DEFAULT 0"))
    if "deleted_at" not in columns:
        sync_conn.execute(text("ALTER TABLE response_sheets ADD COLUMN deleted_at DATETIME"))
    if "deleted_submission_hash" not in columns:
        sync_conn.execute(text("ALTER TABLE response_sheets ADD COLUMN deleted_submission_hash VARCHAR(64)"))
    submission_hash_column = next((column for column in inspector.get_columns("response_sheets") if column["name"] == "submission_hash"), None)
    rebuilt = False
    if submission_hash_column and not submission_hash_column["nullable"]:
        _rebuild_response_sheets_table_with_nullable_submission_hash(sync_conn)
        inspector = inspect(sync_conn)
        rebuilt = True
    if rebuilt:
        return
    indexes = {idx["name"] for idx in inspector.get_indexes("response_sheets")}
    if "ix_response_sheets_is_deleted" not in indexes:
        try:
            sync_conn.execute(text("CREATE INDEX ix_response_sheets_is_deleted ON response_sheets (is_deleted)"))
        except OperationalError as exc:
            if "already exists" not in str(exc).lower():
                raise


def _rebuild_response_sheets_table_with_nullable_submission_hash(sync_conn) -> None:
    sync_conn.execute(text("PRAGMA foreign_keys=OFF"))
    sync_conn.execute(text("ALTER TABLE response_sheets RENAME TO response_sheets_legacy"))
    Base.metadata.create_all(sync_conn)
    sync_conn.execute(
        text(
            """
            INSERT INTO response_sheets (
                id, session_id, submission_hash, is_deleted, deleted_at, deleted_submission_hash,
                paper1_url, paper2_url, candidate_id, candidate_name, raw_parsed, paper_scores,
                section_scores, total_score, max_score, estimated_rank, pool_rank, percentile,
                total_candidates, created_at
            )
            SELECT
                id, session_id, submission_hash, is_deleted, deleted_at, deleted_submission_hash,
                paper1_url, paper2_url, candidate_id, candidate_name, raw_parsed, paper_scores,
                section_scores, total_score, max_score, estimated_rank, pool_rank, percentile,
                total_candidates, created_at
            FROM response_sheets_legacy
            """
        )
    )
    sync_conn.execute(text("DROP TABLE response_sheets_legacy"))
    sync_conn.execute(text("PRAGMA foreign_keys=ON"))
