from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import AsyncSessionLocal, init_db  # noqa: E402
from services.answer_key_importer import import_pdf_answer_keys  # noqa: E402


async def main() -> None:
    await init_db()
    async with AsyncSessionLocal() as session:
        count = await import_pdf_answer_keys(session)
    print(f"Imported {count} answer keys")


if __name__ == "__main__":
    asyncio.run(main())
