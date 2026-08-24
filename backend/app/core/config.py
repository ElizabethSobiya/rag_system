from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Supports `docker compose` and local commands launched from either the
        # repository root or backend/.
        env_file=(PROJECT_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str
    database_url: str

    # OpenAI model config
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    chat_model: str = "gpt-4o"
    chat_temperature: float = 0.1

    # Chunking config
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 50

    # Retrieval config
    top_k_chunks: int = 5
    # Prior exchanges replayed when resolving a follow-up. Older turns are dropped
    # so a long conversation cannot grow the prompt without bound.
    max_history_turns: int = 6
    min_chunk_similarity: float = 0.25
    max_chunks_per_document: int = 2
    # Search-time breadth of the HNSW index walk. Raised from pgvector's default
    # of 40 so the candidate pool is not truncated by the index itself.
    hnsw_ef_search: int = 100

    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # When True, disables /docs and /redoc to reduce attack surface
    disable_openapi: bool = False


settings = Settings()
