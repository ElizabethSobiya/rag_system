import asyncio
import logging
import os
import re
import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rate_limit import upload_limiter
from app.schemas.document import BulkDeleteRequest, BulkDeleteResponse, DocumentContentResponse, DocumentResponse, UploadResponse
from app.services.chunker import chunk_pages
from app.services.embedder import embed_texts
from app.services.parser import parse_document
from app.services.vector_store import (
    delete_document,
    delete_documents_bulk,
    get_all_documents,
    get_document_content,
    get_document_file,
    insert_chunks,
    insert_document,
    update_document_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".txt", ".md", ".csv", ".xlsx"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# Magic-byte signatures for binary formats (text formats are validated by extension only)
_MAGIC_SIGNATURES: dict[str, list[bytes]] = {
    ".pdf": [b"%PDF"],
    ".docx": [b"PK\x03\x04"],  # ZIP-based Office format
    ".xlsx": [b"PK\x03\x04"],  # ZIP-based Office format
}


def _sanitize_filename(raw: str) -> str:
    """Strip path components and dangerous characters from a user-supplied filename."""
    name = os.path.basename(raw)
    # Remove null bytes and control characters
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    # Keep only safe characters: alphanumeric, dot, hyphen, underscore, space
    name = re.sub(r"[^\w.\- ]", "_", name)
    # Collapse consecutive dots/underscores (prevent hidden files like ..foo)
    name = re.sub(r"\.{2,}", ".", name)
    # Limit length
    name = name[:255]
    return name or "document"


def _validate_magic_bytes(file_bytes: bytes, extension: str) -> None:
    """Verify that binary files match their expected magic-byte signatures."""
    signatures = _MAGIC_SIGNATURES.get(extension)
    if signatures is None:
        return  # Text-based formats don't need magic-byte checks
    if not any(file_bytes.startswith(sig) for sig in signatures):
        raise HTTPException(
            status_code=400,
            detail=f"File content does not match the expected format for '{extension}'.",
        )


async def _read_upload(file: UploadFile) -> bytes:
    """Read only enough bytes to validate the configured upload limit."""
    file_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Files must be 25 MB or smaller.")
    return file_bytes


async def _process_document(
    doc_id: uuid.UUID,
    file_bytes: bytes,
    filename: str,
) -> None:
    """Background task: parse → chunk → embed → store."""
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            # Parsing and tokenization are CPU-bound and would otherwise block
            # the FastAPI event loop while a document is being ingested.
            pages = await asyncio.to_thread(parse_document, file_bytes, filename)
            if not pages:
                await update_document_status(
                    db,
                    doc_id=doc_id,
                    status="error",
                    error_msg="No text content extracted from document.",
                )
                return

            chunks = await asyncio.to_thread(chunk_pages, pages)
            if not chunks:
                await update_document_status(
                    db,
                    doc_id=doc_id,
                    status="error",
                    error_msg="Document produced no chunks after splitting.",
                )
                return

            texts = [c.content for c in chunks]
            embeddings = await embed_texts(texts)

            await insert_chunks(db, doc_id=doc_id, chunks=chunks, embeddings=embeddings, auto_commit=False)
            await update_document_status(
                db,
                doc_id=doc_id,
                status="ready",
                chunk_count=len(chunks),
                auto_commit=False,
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.exception("Document processing failed for %s", doc_id)
            await update_document_status(
                db,
                doc_id=doc_id,
                status="error",
                error_msg="Failed to process document. Please try again or upload a different file.",
            )


@router.post("/upload", response_model=UploadResponse, status_code=202)
async def upload_document(
    request: Request,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    collection_name: Annotated[str, Form()] = "General",
):
    upload_limiter.check(request)

    from pathlib import Path

    safe_name = _sanitize_filename(file.filename or "unknown")

    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    file_bytes = await _read_upload(file)
    _validate_magic_bytes(file_bytes, suffix)

    # Sanitize collection name: strip control chars and limit length
    clean_collection = re.sub(r"[^\w.\- ]", "_", collection_name.strip())[:120] or "General"

    doc_id = uuid.uuid4()
    await insert_document(
        db,
        doc_id=doc_id,
        filename=safe_name,
        file_type=suffix.lstrip("."),
        file_size=len(file_bytes),
        file_data=file_bytes,
        collection_name=clean_collection,
    )

    logger.info(
        "Document uploaded: id=%s filename=%s size=%d collection=%s ip=%s",
        doc_id, safe_name, len(file_bytes), clean_collection,
        request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown"),
    )

    background_tasks.add_task(
        _process_document, doc_id, file_bytes, safe_name
    )

    return UploadResponse(
        id=doc_id,
        filename=safe_name,
        status="processing",
        message="Document received and is being processed.",
    )


@router.get("/", response_model=list[DocumentResponse])
async def list_documents(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 100,
    offset: int = 0,
):
    rows = await get_all_documents(db, limit=min(limit, 500), offset=offset)
    return [DocumentResponse(**row) for row in rows]


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_documents(
    request: Request,
    body: BulkDeleteRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not body.document_ids:
        raise HTTPException(status_code=400, detail="No document IDs provided.")
    if len(body.document_ids) > 100:
        raise HTTPException(status_code=400, detail="Cannot delete more than 100 documents at once.")
    deleted = await delete_documents_bulk(db, doc_ids=body.document_ids)
    logger.info(
        "Bulk delete: count=%d ids=%s ip=%s",
        deleted, [str(d) for d in body.document_ids],
        request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown"),
    )
    return BulkDeleteResponse(deleted_count=deleted)


@router.get("/{doc_id}/content", response_model=DocumentContentResponse)
async def get_document_content_endpoint(
    doc_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await get_document_content(db, doc_id=doc_id)
    if not result:
        raise HTTPException(status_code=404, detail="Document not found.")
    if result["status"] != "ready":
        raise HTTPException(status_code=409, detail="Document is still processing.")
    return DocumentContentResponse(
        id=result["id"],
        filename=result["filename"],
        file_type=result["file_type"],
        content=result["content"],
        chunk_count=len(result["chunks"]),
    )


MIME_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "html": "text/html",
    "htm": "text/html",
    "md": "text/markdown",
    "txt": "text/plain",
}


@router.get("/{doc_id}/download")
async def download_document(
    request: Request,
    doc_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await get_document_file(db, doc_id=doc_id)
    if not result:
        raise HTTPException(status_code=404, detail="Document not found.")
    if not result["file_data"]:
        raise HTTPException(status_code=404, detail="Original file data is not available for this document.")
    content_type = MIME_TYPES.get(result["file_type"], "application/octet-stream")
    safe_name = _sanitize_filename(result["filename"])
    logger.info(
        "Document downloaded: id=%s filename=%s ip=%s",
        doc_id, safe_name,
        request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown"),
    )
    # RFC 5987 encoding for non-ASCII filenames
    encoded_name = quote(safe_name)
    return Response(
        content=result["file_data"],
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{doc_id}", status_code=204)
async def remove_document(
    request: Request,
    doc_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    deleted = await delete_document(db, doc_id=doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found.")
    logger.info(
        "Document deleted: id=%s ip=%s",
        doc_id,
        request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown"),
    )
