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
├── docker-compose.yml  # PostgreSQL + pgvector
└── .env.example        # Copy to .env and fill in
```

## Getting started

### 1. Configure environment

```bash
cp .env.example .env
# then edit .env and set OPENAI_API_KEY and any other values
```

### 2. Start the database

```bash
docker compose up -d
```

### 3. Run the backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API runs at http://localhost:8000.

### 4. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

The app runs at http://localhost:5173.

## Environment variables

See [.env.example](.env.example). **Never commit your real `.env`** — it is
gitignored.
