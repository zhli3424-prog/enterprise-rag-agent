from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.config import settings
from app.embeddings import embed_query
from app.models import Chunk, Document, User


@dataclass(frozen=True)
class SearchHit:
    chunk_id: int
    document_id: int
    title: str
    filename: str
    department: str
    page: int | None
    ordinal: int
    content: str
    score: float

    def public_dict(self, include_content: bool = False) -> dict:
        value = asdict(self)
        if not include_content:
            value.pop("content")
        return value


def accessible_documents_query(user: User) -> Select:
    query = select(Document)
    if user.role != "admin":
        query = query.where(Document.department.in_(["all", user.department]))
    return query


def search_knowledge(session: Session, user: User, query: str, limit: int = 5) -> list[SearchHit]:
    query_vector = embed_query(query)
    distance = Chunk.embedding.cosine_distance(query_vector).label("distance")
    statement = (
        select(Chunk, Document, distance)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.status == "ready")
        .order_by(distance)
        .limit(limit)
    )
    if user.role != "admin":
        statement = statement.where(Document.department.in_(["all", user.department]))

    hits = []
    for chunk, document, raw_distance in session.execute(statement):
        score = max(-1.0, min(1.0, 1.0 - float(raw_distance)))
        hits.append(
            SearchHit(
                chunk_id=chunk.id,
                document_id=document.id,
                title=document.title,
                filename=document.original_filename,
                department=document.department,
                page=chunk.page,
                ordinal=chunk.ordinal,
                content=chunk.content,
                score=round(score, 4),
            )
        )
    return hits


def lexical_coverage(query: str, content: str) -> float:
    def bigrams(value: str) -> set[str]:
        normalized = "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", value.lower()))
        return {normalized[index : index + 2] for index in range(len(normalized) - 1)}

    query_terms = bigrams(query)
    return len(query_terms & bigrams(content)) / len(query_terms) if query_terms else 0.0


def evidence_is_sufficient(query: str, hits: list[SearchHit]) -> bool:
    if not hits or hits[0].score < settings.min_retrieval_score:
        return False
    # ponytail: cheap lexical guard; add a reranker only if a larger evaluation set proves this insufficient.
    return max(lexical_coverage(query, hit.content) for hit in hits) >= settings.min_lexical_coverage
