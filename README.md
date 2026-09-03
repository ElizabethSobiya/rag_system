# RAG System

A Retrieval-Augmented Generation (RAG) application with a FastAPI backend and a
React + Vite frontend. Documents are parsed, chunked, embedded, and stored in
PostgreSQL (via `pgvector`); queries are answered by an LLM grounded in the
retrieved chunks.

## Stack

- **Backend:** FastAPI, SQLAlchemy (async), OpenAI, pgvector, PyMuPDF / python-docx
- **Frontend:** React, TypeScript, Vite
- **Database:** PostgreSQL 16 with the `pgvector` extension
- **Infra:** Docker Compose

## Project structure

```
.
├── backend/            # FastAPI app (API, services, models)
├── frontend/           # React + Vite app
├── docker-compose.yml  # Complete local stack
├── render.yaml         # Render Blueprint (deployment)
├── DEPLOY.md           # Deployment walkthrough
└── .env.example        # Copy to .env and fill in
```

## Getting started

### 1. Configure environment

```bash
cp .env.example .env
# then edit .env and set OPENAI_API_KEY and any other values
```

### 2. Start the complete application

```bash
docker compose up --build
```

Open http://localhost:5173. API documentation is available at
http://localhost:8000/docs.

This is the supported local setup. It uses a known Python version and installs
backend dependencies in a container, so users do not need to install Python,
Rust, PostgreSQL, or pgvector locally.

### Optional: run services without Docker

Use this only when developing the backend or frontend directly.

#### Backend

```bash
cd backend
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --reload-exclude '.venv/*'
```

The backend loads the repository `.env` automatically. Ensure Docker is running
the database first and apply the idempotent schema job:

```bash
docker compose up -d db
docker compose up schema
```

Retrieval results below `MIN_CHUNK_SIMILARITY` (default `0.25`) are excluded
before answer generation. API callers can override this for an individual query
with the optional `min_similarity` field (`0.0` to `1.0`).

To keep answers grounded across multiple sources, retrieval prefers at most
`MAX_CHUNKS_PER_DOCUMENT` chunks from each document (default `2`) before
backfilling unused result slots. Queries can override this with the optional
`max_chunks_per_document` field.

Follow-up questions are supported. Callers may send prior exchanges as the
optional `history` field (a list of `{question, answer}` turns); the frontend sends
the current conversation automatically. Because a follow-up like "what about the
second one?" is a poor search query on its own, it is first rewritten into a
standalone question, and that rewrite is what gets embedded and searched. The
rewrite is returned as `search_query` on the response so it stays inspectable, and
any failure falls back to the question as asked. `MAX_HISTORY_TURNS` (default `6`)
bounds how many past exchanges are replayed.

Vector search uses an HNSW index over the chunk embeddings. `HNSW_EF_SEARCH`
(default `100`) controls how widely the index is walked at query time: higher
values improve recall at some cost in latency. It is automatically raised to at
least the size of the candidate pool a query requests, because pgvector returns
fewer rows than asked for when `ef_search` is below the row limit.

#### Frontend

```bash
cd frontend
yarn install --frozen-lockfile
yarn dev
```

The app runs at http://localhost:5173. Use Yarn for this project; its committed
`yarn.lock` guarantees the dependency versions used by the app. Node.js 20 or
later is recommended.

## Deployment

The app deploys to Render (backend container + static frontend) against a
Supabase Postgres database. [`render.yaml`](render.yaml) declares both Render
services; [DEPLOY.md](DEPLOY.md) is the step-by-step walkthrough.

Two things differ from the local setup and are easy to miss:

- `VITE_API_BASE_URL` is read at **build** time and inlined into the bundle, so
  changing it requires a rebuild rather than a restart.
- `CORS_ORIGINS` is parsed as a JSON array (`["https://example.com"]`), not a
  bare hostname.

## Environment variables

See [.env.example](.env.example). **Never commit your real `.env`** — it is
gitignored.
