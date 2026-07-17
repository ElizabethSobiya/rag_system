"""pgvector insert and similarity search helpers."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.chunker import ChunkData


async def insert_document(
    db: AsyncSession,
    *,
    doc_id: uuid.UUID,
    filename: str,
    file_type: str,
    file_size: int,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO documents (id, filename, file_type, file_size, status, created_at, updated_at)
            VALUES (:id, :filename, :file_type, :file_size, 'processing', NOW(), NOW())
            """
        ),
        {
            "id": str(doc_id),
            "filename": filename,
            "file_type": file_type,
            "file_size": file_size,
        },
    )
    await db.commit()


async def insert_chunks(
    db: AsyncSession,
    *,
    doc_id: uuid.UUID,
    chunks: list[ChunkData],
    embeddings: list[list[float]],
) -> None:
    """Bulk-insert chunks with their embeddings."""
    for chunk, embedding in zip(chunks, embeddings):
        await db.execute(
            text(
                """
                INSERT INTO chunks
                    (id, document_id, chunk_index, content, token_count, page_number, embedding, created_at)
                VALUES
                    (:id, :document_id, :chunk_index, :content, :token_count, :page_number,
                     CAST(:embedding AS vector), NOW())
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "document_id": str(doc_id),
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "token_count": chunk.token_count,
                "page_number": chunk.page_number,
                "embedding": str(embedding),
            },
        )
    await db.commit()


async def update_document_status(
    db: AsyncSession,
    *,
    doc_id: uuid.UUID,
    status: str,
    chunk_count: int = 0,
    error_msg: str | None = None,
) -> None:
    await db.execute(
        text(
            """
            UPDATE documents
            SET status = :status,
                chunk_count = :chunk_count,
                error_msg = :error_msg,
                updated_at = NOW()
            WHERE id = :id
            """
        ),
        {
            "id": str(doc_id),
            "status": status,
            "chunk_count": chunk_count,
            "error_msg": error_msg,
        },
    )
    await db.commit()


async def search_similar_chunks(
    db: AsyncSession,
    *,
    query_embedding: list[float],
    top_k: int,
) -> list[dict]:
    """Return top-k chunks ordered by cosine similarity (ascending distance)."""
    result = await db.execute(
        text(
            """
            SELECT
                c.id,
                c.document_id,
                c.chunk_index,
                c.content,
                c.page_number,
                c.token_count,
                (c.embedding <=> CAST(:embedding AS vector)) AS distance,
                d.filename
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.status = 'ready'
              AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
            """
        ),
        {"embedding": str(query_embedding), "top_k": top_k},
    )
    rows = result.mappings().all()
    return [dict(row) for row in rows]


async def get_all_documents(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        text(
            """
            SELECT id, filename, file_type, file_size, chunk_count, status, error_msg,
                   created_at, updated_at
            FROM documents
            ORDER BY created_at DESC
            """
        )
    )
    rows = result.mappings().all()
    return [dict(row) for row in rows]


async def delete_document(db: AsyncSession, *, doc_id: uuid.UUID) -> bool:
    result = await db.execute(
        text("DELETE FROM documents WHERE id = :id"),
        {"id": str(doc_id)},
    )
    await db.commit()
    return result.rowcount > 0
