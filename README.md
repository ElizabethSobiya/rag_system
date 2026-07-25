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

#### Frontend

```bash
cd frontend
yarn install --frozen-lockfile
yarn dev
```

The app runs at http://localhost:5173. Use Yarn for this project; its committed
`yarn.lock` guarantees the dependency versions used by the app. Node.js 20 or
later is recommended.

## Environment variables

See [.env.example](.env.example). **Never commit your real `.env`** — it is
gitignored.
