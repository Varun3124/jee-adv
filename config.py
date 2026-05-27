from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./jee_advanced_2026.db")
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "change-me")
    total_candidates: int = int(os.getenv("TOTAL_CANDIDATES", "180000"))
    rank_buffer_percent: int = int(os.getenv("RANK_BUFFER_PERCENT", "10"))
    app_name: str = "JEE Advanced 2026 Rank Predictor"


@lru_cache
def get_settings() -> Settings:
    return Settings()
