from __future__ import annotations

import logging
import time
from collections.abc import Generator

from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Base, User
from app.security import hash_password

logger = logging.getLogger(__name__)

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

DEMO_USERS = (
    ("admin", "Admin123!", "admin", "all"),
    ("engineer", "Engineer123!", "employee", "engineering"),
    ("finance", "Finance123!", "employee", "finance"),
)


def init_database(max_wait_seconds: int = 45) -> None:
    deadline = time.monotonic() + max_wait_seconds
    while True:
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
                        "ON chunks USING hnsw (embedding vector_cosine_ops)"
                    )
                )
            seed_demo_users()
            return
        except OperationalError:
            if time.monotonic() >= deadline:
                raise
            logger.warning("database unavailable; retrying")
            time.sleep(2)


def seed_demo_users() -> None:
    with SessionLocal() as session:
        if session.scalar(select(User.id).limit(1)) is not None:
            return
        for username, password, role, department in DEMO_USERS:
            session.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                    department=department,
                )
            )
        session.commit()


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
