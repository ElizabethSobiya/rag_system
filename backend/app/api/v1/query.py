from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.query import QueryRequest, QueryResponse
from app.services.embedder import embed_query
from app.services.llm import generate_answer
from app.services.vector_store import search_similar_chunks

router = APIRouter(prefix="/query", tags=["query"])


@router.post("/", response_model=QueryResponse)
async def query_documents(
    request: QueryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    top_k = request.top_k or settings.top_k_chunks

    query_embedding = await embed_query(request.query)

    chunks = await search_similar_chunks(db, query_embedding=query_embedding, top_k=top_k)

    if not chunks:
        raise HTTPException(
            status_code=404,
            detail="No documents are ready for querying. Upload and process a document first.",
        )

    result = await generate_answer(request.query, chunks)

    return QueryResponse(
        query=request.query,
        answer=result["answer"],
        citations=result["citations"],
    )
