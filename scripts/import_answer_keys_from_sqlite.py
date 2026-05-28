from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from database import AsyncSessionLocal, engine, init_db  # noqa: E402
from models import AnswerKey  # noqa: E402


JSON_FIELDS = {
    "correct_answer",
    "correct_option_hash_md5",
    "correct_option_hash_phash",
    "rule_json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy answer_keys rows from a local SQLite database into the configured target database."
    )
    parser.add_argument(
        "source_db",
        type=Path,
        help="Path to the local .db or .sqlite3 file that contains the answer_keys table.",
    )
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Skip recomputing existing submissions after the answer keys are imported.",
    )
    return parser.parse_args()


def load_answer_key_rows(source_db: Path) -> list[dict[str, object]]:
    if not source_db.exists():
        raise FileNotFoundError(f"Source database not found: {source_db}")

    with sqlite3.connect(source_db) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM answer_keys ORDER BY paper, subject, id").fetchall()

    if not rows:
        raise ValueError(f"No rows found in answer_keys for {source_db}")

    normalized_rows: list[dict[str, object]] = []
    for row in rows:
        record = dict(row)
        for field in JSON_FIELDS:
            if field in record:
                record[field] = _decode_json_value(record[field])
        if "created_at" in record:
            record["created_at"] = _decode_datetime_value(record["created_at"])
        normalized_rows.append(record)
    return normalized_rows


async def import_answer_keys_from_sqlite(source_db: Path, refresh_submissions: bool = True) -> int:
    await init_db()
    rows = load_answer_key_rows(source_db)

    async with AsyncSessionLocal() as session:
        await session.execute(AnswerKey.__table__.delete())
        session.add_all(AnswerKey(**row) for row in rows)
        await session.commit()
        await _sync_identity_sequence(session)

        if refresh_submissions:
            from services.answer_key_importer import refresh_existing_submissions  # noqa: E402

            await refresh_existing_submissions(session)
            await session.commit()

    return len(rows)


async def _sync_identity_sequence(session) -> None:
    if engine.dialect.name != "postgresql":
        return

    result = await session.execute(text("SELECT pg_get_serial_sequence('answer_keys', 'id')"))
    sequence_name = result.scalar()
    if not sequence_name:
        return

    await session.execute(
        text("SELECT setval(:sequence_name, COALESCE((SELECT MAX(id) FROM answer_keys), 1), true)"),
        {"sequence_name": sequence_name},
    )
    await session.commit()


def _decode_json_value(value: object) -> object:
    if value is None or isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def _decode_datetime_value(value: object) -> object:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"Could not parse created_at value: {value!r}") from exc
    return value


async def main() -> None:
    args = parse_args()
    count = await import_answer_keys_from_sqlite(args.source_db, refresh_submissions=not args.no_refresh)
    print(f"Imported {count} answer key rows from {args.source_db}")


if __name__ == "__main__":
    asyncio.run(main())