CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS documents (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filename    TEXT NOT NULL,
    file_type   TEXT NOT NULL,
    file_size   INTEGER NOT NULL,
    file_data   BYTEA,
    collection_name TEXT NOT NULL DEFAULT 'General',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'processing',
    error_msg   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Safe for databases created by earlier versions of the project.
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS collection_name TEXT NOT NULL DEFAULT 'General';

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS file_data BYTEA;

CREATE TABLE IF NOT EXISTS chunks (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id   UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index   INTEGER NOT NULL,
    content       TEXT NOT NULL,
    token_count   INTEGER NOT NULL,
    page_number   INTEGER,
    embedding     vector(1536),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- This file runs before any chunk exists. ivfflat derives its lists from the
-- table contents at build time, so an index created here was trained on no rows
-- and kept that clustering as the corpus grew. HNSW builds incrementally, so its
-- graph reflects the rows actually inserted.
DROP INDEX IF EXISTS chunks_embedding_cosine_idx;

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx ON chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS chunks_content_fts_idx ON chunks
    USING GIN (to_tsvector('english', content));

CREATE INDEX IF NOT EXISTS chunks_document_id_idx ON chunks (document_id);

CREATE INDEX IF NOT EXISTS documents_collection_idx ON documents (collection_name);

CREATE INDEX IF NOT EXISTS documents_created_at_idx ON documents (created_at DESC);

CREATE TABLE IF NOT EXISTS search_history (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query           TEXT NOT NULL,
    answer          TEXT NOT NULL,
    citations       JSONB NOT NULL DEFAULT '[]',
    confidence      DOUBLE PRECISION NOT NULL,
    evidence_status TEXT NOT NULL,
    collection_name TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS search_history_created_at_idx
    ON search_history (created_at DESC);
