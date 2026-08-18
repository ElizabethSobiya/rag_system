import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator


_VALID_FILE_TYPES = {"pdf", "docx", "html", "htm", "txt", "md", "csv", "xlsx"}


class QueryRequest(BaseModel):
    query: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
    ]
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    file_types: list[str] = Field(default_factory=list, max_length=10)
    collection_name: str | None = Field(default=None, max_length=120)
    min_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    max_chunks_per_document: int | None = Field(default=None, ge=1, le=20)

    @field_validator("file_types")
    @classmethod
    def validate_file_types(cls, v: list[str]) -> list[str]:
        invalid = set(v) - _VALID_FILE_TYPES
        if invalid:
            raise ValueError(f"Invalid file types: {sorted(invalid)}")
        return v


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


class SearchHistoryResponse(BaseModel):
    id: uuid.UUID
    query: str
    answer: str
    citations: list[Citation]
    confidence: float
    evidence_status: str
    collection_name: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SearchHistoryList(BaseModel):
    items: list[SearchHistoryResponse]
    total: int
