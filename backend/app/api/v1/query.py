from typing import Annotated

import json

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


async def _get_chunks(request: QueryRequest, db: AsyncSession):
    query_embedding = await embed_query(request.query)
    chunks = await search_similar_chunks(
        db, query_embedding=query_embedding, query=request.query,
        top_k=request.top_k or settings.top_k_chunks, document_ids=request.document_ids,
        file_types=request.file_types, collection_name=request.collection_name,
    )
    if not chunks:
        raise HTTPException(status_code=404, detail="No documents are ready for querying. Upload and process a document first.")
    return chunks


@router.post("/", response_model=QueryResponse)
async def query_documents(
    request: QueryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    chunks = await _get_chunks(request, db)

    result = await generate_answer(request.query, chunks)

    similarities = [max(0.0, 1 - float(chunk["distance"])) for chunk in chunks]
    confidence = round(sum(similarities) / len(similarities), 2)
    evidence_status = (
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
    """Server-Sent Events endpoint for token-by-token grounded answers."""
    chunks = await _get_chunks(request, db)

    similarities = [max(0.0, 1 - float(chunk["distance"])) for chunk in chunks]
    confidence = round(sum(similarities) / len(similarities), 2)
    evidence_status = (
        "strongly_supported" if confidence >= 0.72 and len(chunks) >= 2
        else "partially_supported" if confidence >= 0.52
        else "insufficient_evidence"
    )

    async def event_stream():
        async for event in generate_answer_stream(request.query, chunks):
            if event["type"] == "complete":
                event["confidence"] = confidence
                event["evidence_status"] = evidence_status
                event["retrieval_debug"] = [
                    {"filename": chunk["filename"], "page_number": chunk.get("page_number"),
                     "semantic_rank": chunk.get("semantic_rank"), "lexical_rank": chunk.get("lexical_rank"),
                     "similarity": round(max(0.0, 1 - float(chunk["distance"])), 4),
                     "fusion_score": round(float(chunk["rrf_score"]), 5)} for chunk in chunks
                ]
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
