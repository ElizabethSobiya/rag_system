from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Hosted Postgres providers (Supabase, Neon, RDS) hand out libpq-style URLs.
# asyncpg is not libpq: it rejects these parameters outright, so a pasted
# connection string fails on the first query rather than at startup. `sslmode`
# is translated to the `ssl` argument asyncpg does understand; the rest describe
# libpq-only behaviour that asyncpg either performs by default or cannot express.
_LIBPQ_ONLY_PARAMS = frozenset(
    {"channel_binding", "sslrootcert", "sslcert", "sslkey", "target_session_attrs"}
)

# libpq spells the negotiation modes differently from asyncpg. The two "no TLS"
# modes are preserved as-is; everything stricter collapses to asyncpg's
# `require`, which is what a managed provider's URL is asking for.
_SSLMODE_TO_ASYNCPG = {
    "disable": "disable",
    "allow": "prefer",
    "prefer": "prefer",
    "require": "require",
    "verify-ca": "require",
    "verify-full": "require",
}


def normalize_database_url(url: str) -> str:
    """Rewrite a libpq-style Postgres URL into one the asyncpg driver accepts.

    Managed Postgres dashboards give out `postgresql://...?sslmode=require`.
    Both halves of that are wrong for this app: the URL names no driver, so
    SQLAlchemy would reach for psycopg2, and asyncpg raises on `sslmode`.
    Normalizing here means the connection string can be pasted verbatim out of
    the provider's dashboard into DATABASE_URL.
    """
    parts = urlsplit(url)

    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"

    if not scheme.startswith("postgresql+asyncpg"):
        # Some other driver was requested explicitly. Leave it alone.
        return url

    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key in _LIBPQ_ONLY_PARAMS:
            continue
        if key == "sslmode":
            # An explicit `ssl` wins; it is already in asyncpg's vocabulary.
            query.append(("ssl", _SSLMODE_TO_ASYNCPG.get(value, "require")))
            continue
        query.append((key, value))

    seen: set[str] = set()
    deduped = []
    for key, value in reversed(query):
        if key in seen:
            continue
        seen.add(key)
        deduped.append((key, value))
    deduped.reverse()

    return urlunsplit(
        (scheme, parts.netloc, parts.path, urlencode(deduped), parts.fragment)
    )


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

    # Connection pool. The defaults suit a local Postgres that only this process
    # talks to. Behind a hosted connection pooler the budget is shared across
    # every instance of the app, so both values are env-tunable.
    db_pool_size: int = 10
    db_max_overflow: int = 20

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

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        return normalize_database_url(value)


settings = Settings()
