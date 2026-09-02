# Deploying to Render + Supabase

Three pieces: a **Supabase** Postgres database, a **Render** Docker web service
for the FastAPI backend, and a **Render** static site for the React frontend.
[`render.yaml`](render.yaml) declares the two Render services; Supabase is set up
by hand once.

Work through the steps in order — step 3 needs the database URL from step 1, and
step 5 needs URLs that Render only assigns in step 4.

---

## 1. Create the Supabase database

1. Create a project at [supabase.com](https://supabase.com). Save the database
   password it generates; it is shown once and is not recoverable afterwards.
   Pick the region closest to where you will run Render.
2. Enable pgvector: **Database → Extensions**, search `vector`, toggle it on.
3. Apply the schema: **SQL Editor → New query**, paste the whole of
   [`backend/init.sql`](backend/init.sql), and run it. It is idempotent, so
   re-running it later to pick up schema changes is safe.
4. Confirm it worked — **Table Editor** should now list `documents`, `chunks`
   and `search_history`.

## 2. Get the right connection string

This is the step most likely to go wrong, so it is worth being precise.

Go to **Project Settings → Database → Connection string** and choose
**Session pooler**. Copy that URI. It looks like:

```
postgresql://postgres.abcdefghijkl:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres
```

Replace `[YOUR-PASSWORD]` with the password from step 1. If the password
contains `@`, `/`, `:` or `#`, percent-encode it (`@` → `%40`, `/` → `%2F`)
or those characters will be parsed as URL structure.

**Use the pooler, not the direct connection.** Two reasons:

- Supabase's direct database host resolves to **IPv6 only**. Render's outbound
  traffic is IPv4, so a direct URL fails to connect at all — and the error looks
  like a generic network timeout rather than anything about addressing.
- The pooler multiplexes connections, which matters because this app opens a
  pool per instance.

**Session pooler (port 5432), not transaction pooler (port 6543).** The
transaction pooler does not support prepared statements, which asyncpg uses by
default; on 6543 you would additionally need to disable asyncpg's statement
cache. Session mode needs no code change.

You can paste this URL as-is. The app rewrites `postgresql://` to
`postgresql+asyncpg://` and translates `sslmode` into the form asyncpg accepts —
see `normalize_database_url` in
[`backend/app/core/config.py`](backend/app/core/config.py).

## 3. Push your code

Render reads `render.yaml` from GitHub, so the blueprint has to reach the branch
you deploy from. The configuration is committed on `deploy/render-supabase`:

```bash
git push -u origin deploy/render-supabase
```

Open a PR and merge it to `main`, or point Render's blueprint at the branch
directly in step 4.

## 4. Create the Render services

1. In the [Render dashboard](https://dashboard.render.com): **New → Blueprint**,
   connect the `rag_system` repository. Render reads `render.yaml` and proposes
   `rag-api` and `rag-frontend`.
2. It will prompt for the values marked `sync: false`. Fill in what you can now:

   | Service | Variable | Value |
   | --- | --- | --- |
   | `rag-api` | `OPENAI_API_KEY` | your OpenAI key |
   | `rag-api` | `DATABASE_URL` | the session-pooler URI from step 2 |
   | `rag-api` | `CORS_ORIGINS` | `["http://localhost:5173"]` for now — corrected in step 5 |
   | `rag-frontend` | `VITE_API_BASE_URL` | `http://localhost:8000` for now — corrected in step 5 |

3. Apply. The first backend build takes several minutes, mostly compiling
   PyMuPDF and friends.

## 5. Point the two services at each other

Render assigns hostnames only once a service exists, which is why this is a
second pass. You now have something like `https://rag-api.onrender.com` and
`https://rag-frontend.onrender.com`.

1. **`rag-api` → Environment**, set `CORS_ORIGINS` to a **JSON array** holding
   the frontend's URL:

   ```
   ["https://rag-frontend.onrender.com"]
   ```

   The brackets and quotes are required — the setting is typed as a list, and a
   bare hostname will fail to parse at startup. No trailing slash.

2. **`rag-frontend` → Environment**, set `VITE_API_BASE_URL` to the API's URL:

   ```
   https://rag-api.onrender.com
   ```

   No trailing slash, and no `/api/v1` suffix — the frontend appends paths itself.

3. Redeploy **both**. The frontend especially: Vite inlines this value into the
   JavaScript bundle at build time, so a restart alone will not pick it up. Use
   **Manual Deploy → Deploy latest commit**, not "Restart service".

## 6. Verify

```bash
# Backend is alive
curl https://rag-api.onrender.com/health
# -> {"status":"ok"}

# Docs are disabled in production
curl -o /dev/null -w '%{http_code}\n' https://rag-api.onrender.com/docs
# -> 404

# CORS allows the frontend origin
curl -si -X OPTIONS https://rag-api.onrender.com/api/v1/query \
  -H "Origin: https://rag-frontend.onrender.com" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type" | grep -i access-control-allow-origin
# -> access-control-allow-origin: https://rag-frontend.onrender.com
```

Then open the frontend, upload a document, wait for it to finish processing, and
ask a question about it. That exercises the whole path: upload → parse → chunk →
embed → store → retrieve → answer.

---

## Things worth knowing

**Cold starts.** On Render's free plan the API sleeps after 15 minutes idle and
takes roughly 50 seconds to wake. The first request after a quiet period will
look like the app is broken. `plan: starter` in `render.yaml` removes this.

**Memory.** The free plan caps at 512MB, and PyMuPDF plus tiktoken put this image
near that ceiling. If the logs show the service restarting during uploads, that is
an out-of-memory kill — move to `starter`.

**Connection budget.** `DB_POOL_SIZE=5` and `DB_MAX_OVERFLOW=5` in `render.yaml`
mean each API instance can hold 10 connections. Supabase's free tier pooler
allows far more, but if you scale to several instances, keep
`instances × (pool + overflow)` under your project's limit.

**Rate limiting is per instance.** The limiter in
[`backend/app/middleware/rate_limit.py`](backend/app/middleware/rate_limit.py)
keeps its counters in process memory. With one instance the documented limits
hold exactly; with N instances the effective limit is N times higher, and counters
reset on every deploy. Moving to a shared store would be needed for a real
multi-instance limit.

**Secrets.** `.env` is gitignored and nothing secret is committed. Set
`OPENAI_API_KEY` and `DATABASE_URL` only through Render's environment settings —
they are the two values worth guarding here.

**Schema changes.** There is no migration runner wired into the deploy. After
editing `backend/init.sql`, re-run it in the Supabase SQL editor. It is written
to be idempotent, but note that `CREATE TABLE IF NOT EXISTS` will not alter a
table that already exists — column changes need their own `ALTER TABLE ... IF NOT
EXISTS` line, as the existing ones show.

**Costs.** Render free tier and Supabase free tier are both $0. OpenAI usage is
not: every upload embeds each chunk, and every query embeds the question and runs
a `gpt-4o` completion. Set a spend limit in the OpenAI dashboard before making
the URL public.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| API logs a network timeout connecting to Postgres | Using the direct connection string (IPv6-only) instead of the pooler. Back to step 2. |
| `TypeError: connect() got an unexpected keyword argument 'sslmode'` | A `DATABASE_URL` that bypassed normalization. Confirm it starts with `postgresql://` or `postgresql+asyncpg://`. |
| `prepared statement "__asyncpg_stmt_x__" does not exist` | You are on the transaction pooler (port 6543). Switch to session pooler on 5432. |
| Browser console: blocked by CORS policy | `CORS_ORIGINS` is not a JSON array, has a trailing slash, or the API was not redeployed after the change. |
| Frontend requests go to `localhost:8000` | The frontend was restarted rather than rebuilt. Deploy latest commit so Vite re-inlines the value. |
| `type "vector" does not exist` when applying the schema | pgvector was not enabled. Step 1.2. |
| Uploads succeed, queries return nothing | Documents may still be processing, or `MIN_CHUNK_SIMILARITY` is filtering everything out. Check document status in the UI first. |
