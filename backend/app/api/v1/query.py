"""Grounded question-answering endpoints."""
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.query import QueryRequest, QueryResponse
from app.services.embedder import embed_query
from app.services.llm import generate_answer, generate_answer_stream
from app.services.vector_store import search_similar_chunks

router = APIRouter(prefix="/query", tags=["query"])


def _filter_by_similarity(chunks: list[dict], min_similarity: float) -> list[dict]:
    """Discard retrieval results that are too weak to safely ground an answer."""
    return [
        chunk
        for chunk in chunks
        if 1 - float(chunk["distance"]) >= min_similarity
    ]


def _select_diverse_chunks(
    chunks: list[dict], *, top_k: int, max_per_document: int
) -> list[dict]:
    """Prefer source diversity, then backfill when too few documents are available."""
    selected: list[dict] = []
    skipped: list[dict] = []
    per_document: dict[str, int] = {}

    for chunk in chunks:
        document_id = str(chunk["document_id"])
        count = per_document.get(document_id, 0)
        if count < max_per_document:
            selected.append(chunk)
            per_document[document_id] = count + 1
        else:
            skipped.append(chunk)

    # Do not return fewer results merely because the corpus contains one source.
    selected.extend(skipped[: max(0, top_k - len(selected))])
    return selected[:top_k]


async def _get_chunks(request: QueryRequest, db: AsyncSession) -> list[dict]:
    query_embedding = await embed_query(request.query)
    top_k = request.top_k or settings.top_k_chunks
    chunks = await search_similar_chunks(
        db,
        query_embedding=query_embedding,
        query=request.query,
        # Retrieve extra candidates so the diversity pass has alternatives.
        top_k=top_k * 2,
        document_ids=request.document_ids,
        file_types=request.file_types,
        collection_name=request.collection_name,
    )
    if not chunks:
        raise HTTPException(
            status_code=404,
            detail="No documents are ready for querying. Upload and process a document first.",
        )

    min_similarity = (
        request.min_similarity
        if request.min_similarity is not None
        else settings.min_chunk_similarity
    )
    relevant_chunks = _filter_by_similarity(chunks, min_similarity)
    if not relevant_chunks:
        raise HTTPException(
            status_code=404,
            detail=(
                "No sufficiently relevant context was found for this query "
                f"(minimum similarity: {min_similarity:.2f})."
            ),
        )
    max_per_document = (
        request.max_chunks_per_document
        if request.max_chunks_per_document is not None
        else settings.max_chunks_per_document
    )
    return _select_diverse_chunks(
        relevant_chunks,
        top_k=top_k,
        max_per_document=max_per_document,
    )


def _evidence_metadata(chunks: list[dict]) -> tuple[float, str, list[dict]]:
    similarities = [max(0.0, 1 - float(chunk["distance"])) for chunk in chunks]
    confidence = round(sum(similarities) / len(similarities), 2)
    status = (
        "strongly_supported" if confidence >= 0.72 and len(chunks) >= 2
        else "partially_supported" if confidence >= 0.52
        else "insufficient_evidence"
    )
    debug = [
        {
            "chunk_id": str(chunk["id"]),
            "filename": chunk["filename"],
            "page_number": chunk.get("page_number"),
            "semantic_rank": chunk.get("semantic_rank"),
            "lexical_rank": chunk.get("lexical_rank"),
            "similarity": round(max(0.0, 1 - float(chunk["distance"])), 4),
            "fusion_score": round(float(chunk["rrf_score"]), 5),
        }
        for chunk in chunks
    ]
    return confidence, status, debug


@router.post("/", response_model=QueryResponse)
async def query_documents(
    request: QueryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    chunks = await _get_chunks(request, db)
    result = await generate_answer(request.query, chunks)
    confidence, evidence_status, debug = _evidence_metadata(chunks)
    return QueryResponse(
        query=request.query,
        answer=result["answer"],
        citations=result["citations"],
        confidence=confidence,
        evidence_status=evidence_status,
        retrieval_debug=debug,
    )


@router.post("/stream")
async def stream_query_documents(
    request: QueryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return token-by-token grounded answers as server-sent events."""
    chunks = await _get_chunks(request, db)
    confidence, evidence_status, debug = _evidence_metadata(chunks)

    async def event_stream():
        async for event in generate_answer_stream(request.query, chunks):
            if event["type"] == "complete":
                event.update(
                    confidence=confidence,
                    evidence_status=evidence_status,
                    retrieval_debug=debug,
                )
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
