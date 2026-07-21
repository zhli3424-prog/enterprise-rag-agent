from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, or_, select

from app.config import settings
from app.database import SessionLocal, init_database
from app.embeddings import embed_documents
from app.models import Chunk, Document, IngestionJob
from app.parsing import chunk_parts, parse_document

logging.basicConfig(
    level=settings.log_level,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)
logger = logging.getLogger(__name__)


def claim_job() -> int | None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        job = session.scalar(
            select(IngestionJob)
            .where(
                IngestionJob.status.in_(["pending", "retry"]),
                IngestionJob.available_at <= now,
            )
            .order_by(IngestionJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        job.status = "processing"
        job.locked_at = now
        job.attempts += 1
        job.document.status = "processing"
        session.commit()
        return job.id


def process_job(job_id: int) -> None:
    with SessionLocal() as session:
        job = session.get(IngestionJob, job_id)
        if job is None:
            return
        try:
            parts = parse_document(Path(job.document.stored_path))
            chunks = chunk_parts(parts)
            if not chunks:
                raise ValueError("document produced no chunks")
            vectors = embed_documents([chunk.content for chunk in chunks])
            session.execute(delete(Chunk).where(Chunk.document_id == job.document_id))
            session.add_all(
                Chunk(
                    document_id=job.document_id,
                    page=chunk.page,
                    ordinal=chunk.ordinal,
                    content=chunk.content,
                    embedding=vector,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            )
            job.status = "complete"
            job.error = None
            job.document.status = "ready"
            job.document.error = None
            session.commit()
            logger.info("ingestion complete document_id=%s chunks=%s", job.document_id, len(chunks))
        except Exception as exc:
            session.rollback()
            job = session.get(IngestionJob, job_id)
            if job is None:
                return
            message = str(exc)[:2000]
            job.error = message
            job.document.error = message
            if job.attempts < job.max_attempts:
                job.status = "retry"
                job.document.status = "pending"
                job.available_at = datetime.now(timezone.utc) + timedelta(seconds=5 * (2 ** (job.attempts - 1)))
            else:
                job.status = "failed"
                job.document.status = "failed"
            session.commit()
            logger.exception("ingestion failed document_id=%s", job.document_id)


def recover_stale_jobs() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    with SessionLocal() as session:
        jobs = session.scalars(
            select(IngestionJob).where(
                IngestionJob.status == "processing",
                or_(IngestionJob.locked_at.is_(None), IngestionJob.locked_at < cutoff),
            )
        )
        for job in jobs:
            job.status = "retry"
            job.available_at = datetime.now(timezone.utc)
            job.document.status = "pending"
        session.commit()


def main() -> None:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    init_database()
    recover_stale_jobs()
    logger.info("ingestion worker started")
    while True:
        job_id = claim_job()
        if job_id is None:
            time.sleep(2)
            continue
        process_job(job_id)


if __name__ == "__main__":
    main()
