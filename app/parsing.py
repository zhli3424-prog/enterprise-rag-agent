from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourcePart:
    page: int | None
    text: str


@dataclass(frozen=True)
class TextChunk:
    page: int | None
    ordinal: int
    content: str


def validate_upload_content(path: Path, suffix: str) -> None:
    """Reject files whose bytes do not match their allowed extension."""
    suffix = suffix.lower()
    if suffix == ".pdf":
        if not path.read_bytes()[:5] == b"%PDF-":
            raise ValueError("file content is not a PDF")
        return
    if suffix == ".docx":
        if not zipfile.is_zipfile(path):
            raise ValueError("file content is not a DOCX")
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
        if not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
            raise ValueError("file content is not a DOCX")
        return
    if suffix in {".md", ".markdown"}:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Markdown must be UTF-8 text") from exc
        if "\x00" in text:
            raise ValueError("Markdown must be plain text")
        return
    raise ValueError(f"unsupported file type: {suffix}")


def parse_document(path: Path) -> list[SourcePart]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix == ".docx":
        return _parse_docx(path)
    if suffix in {".md", ".markdown"}:
        return [SourcePart(page=1, text=path.read_text(encoding="utf-8-sig"))]
    raise ValueError(f"unsupported file type: {suffix}")


def _parse_pdf(path: Path) -> list[SourcePart]:
    from pypdf import PdfReader

    pages = []
    for number, page in enumerate(PdfReader(str(path)).pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(SourcePart(page=number, text=text))
    if not pages:
        raise ValueError("PDF has no extractable text; scanned PDFs require OCR and are not supported")
    return pages


def _parse_docx(path: Path) -> list[SourcePart]:
    from docx import Document as DocxDocument

    paragraphs = [paragraph.text.strip() for paragraph in DocxDocument(str(path)).paragraphs]
    text = "\n\n".join(paragraph for paragraph in paragraphs if paragraph)
    if not text:
        raise ValueError("DOCX has no extractable paragraphs")
    # Word pagination depends on the renderer and cannot be inferred from paragraph XML.
    return [SourcePart(page=None, text=text)]


def chunk_parts(parts: list[SourcePart], target_size: int = 700, overlap: int = 100) -> list[TextChunk]:
    if target_size <= overlap or overlap < 0:
        raise ValueError("target_size must be greater than overlap")
    chunks: list[TextChunk] = []
    for part in parts:
        for content in chunk_text(part.text, target_size=target_size, overlap=overlap):
            chunks.append(TextChunk(page=part.page, ordinal=len(chunks), content=content))
    return chunks


def chunk_text(text: str, target_size: int = 700, overlap: int = 100) -> list[str]:
    """Split on paragraph boundaries and retain a small character overlap."""
    normalized = re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n"))
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n|(?<=[。！？!?])\s*\n", normalized) if item.strip()]
    if not paragraphs:
        return []

    pieces: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= target_size:
            pieces.append(paragraph)
            continue
        start = 0
        while start < len(paragraph):
            end = min(start + target_size, len(paragraph))
            pieces.append(paragraph[start:end])
            if end == len(paragraph):
                break
            start = end - overlap

    result: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}".strip() if current else piece
        if len(candidate) <= target_size:
            current = candidate
            continue
        if current:
            result.append(current)
            prefix = current[-overlap:] if overlap else ""
            current = f"{prefix}\n\n{piece}".strip()
            if len(current) > target_size:
                result.append(current[:target_size])
                current = current[target_size - overlap :]
        else:
            result.append(piece)
            current = ""
    if current:
        result.append(current)
    return [item for item in result if item.strip()]
