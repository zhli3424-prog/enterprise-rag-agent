from __future__ import annotations

import logging
import threading

from app.config import settings

logger = logging.getLogger(__name__)

_model = None
_model_lock = threading.Lock()
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


def get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                logger.info("loading embedding model", extra={"model": settings.embedding_model})
                _model = SentenceTransformer(
                    settings.embedding_model,
                    device="cpu",
                    local_files_only=settings.embedding_local_files_only,
                )
    return _model


def embed_documents(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors = get_model().encode(texts, normalize_embeddings=True, batch_size=16, show_progress_bar=False)
    return [vector.tolist() for vector in vectors]


def embed_query(query: str) -> list[float]:
    vector = get_model().encode([QUERY_PREFIX + query], normalize_embeddings=True, show_progress_bar=False)[0]
    return vector.tolist()


def embedding_loaded() -> bool:
    return _model is not None

