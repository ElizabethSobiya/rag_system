import uuid

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    file_types: list[str] = Field(default_factory=list)
    collection_name: str | None = Field(default=None, max_length=120)


class Citation(BaseModel):
    index: int
    filename: str
    page_number: int | None
    excerpt: str
    similarity: float
    referenced: bool


class QueryResponse(BaseModel):
    query: str
    answer: str
    citations: list[Citation]
    confidence: float
    evidence_status: str
    retrieval_debug: list[dict]
