import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.document import DocumentResponse, UploadResponse
from app.services.chunker import chunk_pages
from app.services.embedder import embed_texts
from app.services.parser import parse_document
from app.services.vector_store import (
    delete_document,
    get_all_documents,
    insert_chunks,
    insert_document,
    update_document_status,
)

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".txt", ".md", ".csv", ".xlsx"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


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
            await update_document_status(
                db,
                doc_id=doc_id,
                status="error",
                error_msg=str(exc)[:500],
            )


@router.post("/upload", response_model=UploadResponse, status_code=202)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    collection_name: Annotated[str, Form()] = "General",
):
    from pathlib import Path

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    file_bytes = await _read_upload(file)

    doc_id = uuid.uuid4()
    await insert_document(
        db,
        doc_id=doc_id,
        filename=file.filename or "unknown",
        file_type=suffix.lstrip("."),
        file_size=len(file_bytes),
        collection_name=collection_name.strip()[:120] or "General",
    )

    background_tasks.add_task(
        _process_document, doc_id, file_bytes, file.filename or "unknown"
    )

    return UploadResponse(
        id=doc_id,
        filename=file.filename or "unknown",
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


@router.delete("/{doc_id}", status_code=204)
async def remove_document(
    doc_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    deleted = await delete_document(db, doc_id=doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found.")
