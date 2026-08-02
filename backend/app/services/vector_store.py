"""pgvector insert and similarity search helpers."""
import uuid

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
    collection_name: str = "General",
    auto_commit: bool = True,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO documents (id, filename, file_type, file_size, collection_name, status, created_at, updated_at)
            VALUES (:id, :filename, :file_type, :file_size, :collection_name, 'processing', NOW(), NOW())
            """
        ),
        {
            "id": str(doc_id),
            "filename": filename,
            "file_type": file_type,
            "file_size": file_size,
            "collection_name": collection_name,
        },
    )
    if auto_commit:
        await db.commit()


async def insert_chunks(
    db: AsyncSession,
    *,
    doc_id: uuid.UUID,
    chunks: list[ChunkData],
    embeddings: list[list[float]],
    auto_commit: bool = True,
) -> None:
    """Insert all chunks in one database round trip."""
    if len(chunks) != len(embeddings):
        raise ValueError("Each chunk must have exactly one embedding.")

    statement = text(
        """
        INSERT INTO chunks
            (id, document_id, chunk_index, content, token_count, page_number, embedding, created_at)
        VALUES
            (:id, :document_id, :chunk_index, :content, :token_count, :page_number,
             CAST(:embedding AS vector), NOW())
        """
    )
    values = [
        {
            "id": str(uuid.uuid4()),
            "document_id": str(doc_id),
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "token_count": chunk.token_count,
            "page_number": chunk.page_number,
            "embedding": "[" + ",".join(f"{v:.8f}" for v in embedding) + "]",
        }
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]
    if values:
        await db.execute(statement, values)
    if auto_commit:
        await db.commit()


async def update_document_status(
    db: AsyncSession,
    *,
    doc_id: uuid.UUID,
    status: str,
    chunk_count: int = 0,
    error_msg: str | None = None,
    auto_commit: bool = True,
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
    if auto_commit:
        await db.commit()


async def search_similar_chunks(
    db: AsyncSession,
    *,
    query_embedding: list[float],
    query: str,
    top_k: int,
    document_ids: list[uuid.UUID] | None = None,
    file_types: list[str] | None = None,
    collection_name: str | None = None,
) -> list[dict]:
    """Hybrid vector + full-text retrieval combined with reciprocal-rank fusion."""
    filters = ["d.status = 'ready'", "c.embedding IS NOT NULL"]
    params: dict = {"embedding": str(query_embedding), "top_k": top_k, "candidate_k": top_k * 4}
    if document_ids:
        filters.append("c.document_id = ANY(CAST(:document_ids AS uuid[]))")
        params["document_ids"] = [str(doc_id) for doc_id in document_ids]
    if file_types:
        filters.append("d.file_type = ANY(CAST(:file_types AS text[]))")
        params["file_types"] = file_types
    if collection_name:
        filters.append("d.collection_name = :collection_name")
        params["collection_name"] = collection_name
    where_clause = " AND ".join(filters)
    result = await db.execute(
        text(
            f"""
            WITH semantic AS (
                SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> CAST(:embedding AS vector)) AS semantic_rank
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE {where_clause}
                ORDER BY c.embedding <=> CAST(:embedding AS vector) LIMIT :candidate_k
            ), lexical AS (
                SELECT id, row_number() OVER (ORDER BY rank DESC) AS lexical_rank
                FROM (
                    SELECT c.id,
                           ts_rank_cd(to_tsvector('english', c.content), websearch_to_tsquery('english', :query)) AS rank
                    FROM chunks c JOIN documents d ON d.id = c.document_id
                    WHERE {where_clause}
                      AND to_tsvector('english', c.content) @@ websearch_to_tsquery('english', :query)
                ) sub
                ORDER BY rank DESC LIMIT :candidate_k
            ), candidates AS (
                SELECT COALESCE(s.id, l.id) AS id,
                  COALESCE(1.0 / (60 + s.semantic_rank), 0) + COALESCE(1.0 / (60 + l.lexical_rank), 0) AS rrf_score,
                  s.semantic_rank, l.lexical_rank
                FROM semantic s FULL OUTER JOIN lexical l ON s.id = l.id
            )
            SELECT c.id, c.document_id, c.chunk_index, c.content, c.page_number, c.token_count,
                (c.embedding <=> CAST(:embedding AS vector)) AS distance, d.filename, d.collection_name,
                candidates.rrf_score, candidates.semantic_rank, candidates.lexical_rank
            FROM candidates JOIN chunks c ON c.id = candidates.id JOIN documents d ON d.id = c.document_id
            ORDER BY candidates.rrf_score DESC LIMIT :top_k
            """
        ),
        {**params, "query": query},
    )
    rows = result.mappings().all()
    return [dict(row) for row in rows]


async def get_all_documents(
    db: AsyncSession,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    result = await db.execute(
        text(
            """
            SELECT id, filename, file_type, file_size, collection_name, chunk_count, status, error_msg,
                   created_at, updated_at
            FROM documents
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {"limit": limit, "offset": offset},
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
