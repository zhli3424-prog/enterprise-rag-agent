from __future__ import annotations

import hashlib
import logging
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_session, init_database
from app.embeddings import embedding_loaded
from app.models import Chunk, Conversation, Document, IngestionJob, User
from app.rag import stream_rag_answer
from app.retrieval import accessible_documents_query
from app.security import create_session, read_session, verify_password

logging.basicConfig(
    level=settings.log_level,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)
logger = logging.getLogger(__name__)

ALLOWED_SUFFIXES = {".pdf", ".docx", ".md", ".markdown"}
ALLOWED_DEPARTMENTS = {"all", "engineering", "finance"}
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if len(settings.session_secret) < 32 or settings.session_secret.startswith("replace-with-"):
        raise RuntimeError("SESSION_SECRET must be replaced with at least 32 random characters")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    init_database()
    yield


app = FastAPI(title="Enterprise Knowledge Agent", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    conversation_id: int | None = None


def user_public(user: User) -> dict:
    return {"id": user.id, "username": user.username, "role": user.role, "department": user.department}


def current_user(
    session_token: str | None = Cookie(default=None),
    session: Session = Depends(get_session),
) -> User:
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    user_id = read_session(session_token, settings.session_secret)
    user = session.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired session")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin role required")
    return user


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/auth/login")
def login(payload: LoginRequest, response: Response, session: Session = Depends(get_session)) -> dict:
    user = session.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_session(user.id, settings.session_secret, settings.session_ttl_seconds)
    response.set_cookie(
        "session_token",
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
    )
    return {"user": user_public(user)}


@app.post("/api/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie("session_token")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"user": user_public(user)}


@app.post("/api/documents", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    title: str = Form(..., min_length=1, max_length=255),
    department: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(admin_user),
    session: Session = Depends(get_session),
) -> dict:
    if department not in ALLOWED_DEPARTMENTS:
        raise HTTPException(status_code=422, detail="invalid department")
    safe_name = re.split(r"[/\\]", file.filename or "document")[-1]
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="only PDF, DOCX and Markdown files are supported")

    temporary = settings.upload_dir / f".{uuid.uuid4().hex}.part"
    stored: Path | None = None
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary.open("wb") as output:
            while block := await file.read(1024 * 1024):
                size += len(block)
                if size > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="file exceeds the 20 MB limit")
                digest.update(block)
                output.write(block)
        file_hash = digest.hexdigest()
        existing = session.scalar(select(Document).where(Document.file_hash == file_hash))
        if existing:
            raise HTTPException(status_code=409, detail=f"duplicate document: {existing.title}")

        stored = settings.upload_dir / f"{uuid.uuid4().hex}{suffix}"
        temporary.replace(stored)
        document = Document(
            title=title.strip(),
            original_filename=safe_name,
            stored_path=str(stored),
            file_hash=file_hash,
            media_type=file.content_type or "application/octet-stream",
            department=department,
            status="pending",
            uploaded_by=user.id,
        )
        session.add(document)
        session.flush()
        job = IngestionJob(document_id=document.id, status="pending")
        session.add(job)
        session.commit()
        return {"document": document_public(document, chunk_count=0), "job_id": job.id}
    except HTTPException:
        if stored is not None:
            stored.unlink(missing_ok=True)
        raise
    except IntegrityError:
        session.rollback()
        if stored is not None:
            stored.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="duplicate document") from None
    except Exception:
        session.rollback()
        if stored is not None:
            stored.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
        temporary.unlink(missing_ok=True)


def document_public(document: Document, chunk_count: int | None = None) -> dict:
    value = {
        "id": document.id,
        "title": document.title,
        "filename": document.original_filename,
        "department": document.department,
        "status": document.status,
        "error": document.error,
        "created_at": document.created_at.isoformat() if document.created_at else None,
    }
    if chunk_count is not None:
        value["chunk_count"] = chunk_count
    return value


@app.get("/api/documents")
def list_documents(user: User = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    statement = (
        accessible_documents_query(user)
        .add_columns(func.count(Chunk.id).label("chunk_count"))
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .group_by(Document.id)
        .order_by(Document.created_at.desc())
    )
    documents = [document_public(document, count) for document, count in session.execute(statement)]
    return {"documents": documents}


def authorized_document(document_id: int, user: User, session: Session) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    if user.role != "admin" and document.department not in {"all", user.department}:
        raise HTTPException(status_code=404, detail="document not found")
    return document


@app.get("/api/documents/{document_id}/status")
def document_status(document_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    document = authorized_document(document_id, user, session)
    count = session.scalar(select(func.count(Chunk.id)).where(Chunk.document_id == document.id)) or 0
    return {"document": document_public(document, count)}


@app.post("/api/documents/{document_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_document(
    document_id: int,
    _: User = Depends(admin_user),
    session: Session = Depends(get_session),
) -> dict:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    if document.status != "failed":
        raise HTTPException(status_code=409, detail="only failed documents can be retried")
    job = IngestionJob(document_id=document.id, status="pending")
    document.status = "pending"
    document.error = None
    session.add(job)
    session.commit()
    return {"job_id": job.id}


@app.delete("/api/documents/{document_id}")
def delete_document(
    document_id: int,
    _: User = Depends(admin_user),
    session: Session = Depends(get_session),
) -> dict:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    stored_path = Path(document.stored_path)
    session.delete(document)
    session.commit()
    stored_path.unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/chat/stream")
def chat_stream(payload: ChatRequest, user: User = Depends(current_user), session: Session = Depends(get_session)):
    question = re.sub(r"\s+", " ", payload.question).strip()
    if payload.conversation_id is not None:
        conversation = session.get(Conversation, payload.conversation_id)
        if conversation is None or conversation.user_id != user.id:
            raise HTTPException(status_code=404, detail="conversation not found")
    return StreamingResponse(
        stream_rag_answer(user.id, question, payload.conversation_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/health")
def health(session: Session = Depends(get_session)) -> dict:
    session.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "database": "ok",
        "deepseek_configured": bool(settings.deepseek_api_key),
        "embedding_model": settings.embedding_model,
        "embedding_loaded": embedding_loaded(),
    }
