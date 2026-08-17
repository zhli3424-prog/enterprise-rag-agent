from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://knowledge_agent:change-this-database-password@localhost:5432/knowledge_agent",
    )
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    embedding_local_files_only: bool = _bool_env("EMBEDDING_LOCAL_FILES_ONLY")
    session_secret: str = os.getenv("SESSION_SECRET", "dev-only-change-me")
    session_ttl_seconds: int = int(os.getenv("SESSION_TTL_SECONDS", "28800"))
    cookie_secure: bool = _bool_env("COOKIE_SECURE")
    min_retrieval_score: float = float(os.getenv("MIN_RETRIEVAL_SCORE", "0.35"))
    min_lexical_coverage: float = float(os.getenv("MIN_LEXICAL_COVERAGE", "0.18"))
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", "data/uploads"))
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
    job_stale_seconds: int = int(os.getenv("JOB_STALE_SECONDS", "900"))
    job_recovery_interval_seconds: int = int(os.getenv("JOB_RECOVERY_INTERVAL_SECONDS", "30"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()


settings = Settings()
