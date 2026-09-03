# Deploying to Render + Supabase + Vercel

Three pieces: a **Supabase** Postgres database, a **Render** Docker web service
for the FastAPI backend, and a **Vercel** project for the React frontend.
[`render.yaml`](render.yaml) declares the Render service; Vercel builds the
frontend from its own project settings, with
[`frontend/vercel.json`](frontend/vercel.json) adding response headers. Supabase
is set up by hand once.

Work through the steps in order — step 3 needs the database URL from step 1, and
step 6 needs hostnames that Render and Vercel only assign once each service has
been created.

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

**Append `?sslmode=require`.** The URL works without it, but the failure mode is
worth avoiding. With no `sslmode`, asyncpg defaults to `prefer`: it connects with
TLS, and if the server rejects *authorization* it assumes TLS was the problem and
silently retries in plaintext. The pooler refuses plaintext, so a simple wrong
password surfaces as a confusing second-attempt connection error with the real
`InvalidPasswordError` nowhere in the traceback. `sslmode=require` skips the
retry, so authentication failures say so.

You can otherwise paste this URL as-is. The app rewrites `postgresql://` to
`postgresql+asyncpg://` and translates `sslmode` into the form asyncpg accepts —
see `normalize_database_url` in
[`backend/app/core/config.py`](backend/app/core/config.py).

## 3. Push your code

Render reads `render.yaml` from GitHub, so the blueprint has to reach the branch
you deploy from, and Vercel builds whatever branch you point the project at.
The configuration lives on `dev`:

```bash
git push origin dev
```

Point both Render's blueprint and the Vercel project at `dev`, or merge to `main`
and deploy from there.

## 4. Create the Render service (backend)

1. In the [Render dashboard](https://dashboard.render.com): **New → Blueprint**,
   connect the `rag_system` repository. Render reads `render.yaml` and proposes
   `rag-api`. Use Blueprint rather than "Web Service" — the blueprint carries the
   Docker paths, health check and pool sizing.
2. It will prompt for the values marked `sync: false`:

   | Variable | Value |
   | --- | --- |
   | `OPENAI_API_KEY` | your OpenAI key |
   | `DATABASE_URL` | the session-pooler URI from step 2 |
   | `CORS_ORIGINS` | leave blank for now — set in step 6 |

   `CORS_ORIGINS` has no correct value yet because the frontend does not exist.
   Left unset it falls back to the localhost defaults in
   [`backend/app/core/config.py`](backend/app/core/config.py), which is harmless
   and lets you run the frontend locally against the deployed API.

3. Apply. The first backend build takes several minutes, mostly compiling
   PyMuPDF and friends.
4. Confirm before going on, and copy the hostname exactly — Render appends a
   suffix if the name was taken:

   ```bash
   curl https://rag-api.onrender.com/health   # -> {"status":"ok"}
   ```

## 5. Create the Vercel project (frontend)

1. In [Vercel](https://vercel.com): **Add New → Project**, import `rag_system`.
   Point it at the branch you deploy from — it defaults to `main`, so a fix
   pushed only to `dev` will not be built.
2. **Settings → General → Root Directory: `frontend`.** The repository root has
   no `package.json`, so a build from there fails at the install step before it
   reaches any frontend code.
3. Leave **Build & Development Settings** on their defaults, with every override
   toggled off. Vercel detects Vite inside `frontend/` and derives
   `yarn install` / `yarn build` / `dist` on its own; a stale Build or Install
   Command override saved on the project silently wins over that detection and
   is worth checking first when a build fails.
   [`frontend/vercel.json`](frontend/vercel.json) only adds response headers — it
   deliberately sets no build fields, so there is one source of truth.
4. **Settings → Environment Variables**, add for *Production* (and *Preview* if
   you want preview deployments to reach the API):

   ```
   VITE_API_BASE_URL = https://rag-api.onrender.com
   ```

   No trailing slash, and no `/api/v1` suffix — the frontend appends paths
   itself. This is the only variable the frontend reads; it is the sole
   `import.meta.env` reference in the source.

5. **Deployments → Redeploy.** Vite inlines this value into the JavaScript bundle
   at build time, so any build that ran before the variable existed still has the
   `http://localhost:8000` fallback from
   [`frontend/src/App.tsx`](frontend/src/App.tsx) baked in. A redeploy is
   required; there is nothing to restart.

## 6. Let the API accept the frontend's origin

**`rag-api` → Environment**, set `CORS_ORIGINS` to the Vercel production URL:

```
https://rag-system.vercel.app
```

Several origins are comma-separated; a JSON array works too. Trailing slashes are
stripped for you, since one would otherwise never match the `Origin` header a
browser sends. Then **Manual Deploy → Deploy latest commit**; the value is read
once at startup.

## 7. Verify

```bash
# Backend is alive
curl https://rag-api.onrender.com/health
# -> {"status":"ok"}

# Docs are disabled in production
curl -o /dev/null -w '%{http_code}\n' https://rag-api.onrender.com/docs
# -> 404

# CORS allows the frontend origin
curl -si -X OPTIONS https://rag-api.onrender.com/api/v1/query \
  -H "Origin: https://rag-system.vercel.app" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type" | grep -i access-control-allow-origin
# -> access-control-allow-origin: https://rag-system.vercel.app
```

Then open the frontend, upload a document, wait for it to finish processing, and
ask a question about it. That exercises the whole path: upload → parse → chunk →
embed → store → retrieve → answer.

---

## Things worth knowing

**Cold starts.** On Render's free plan the API sleeps after 15 minutes idle and
takes roughly 50 seconds to wake. Vercel does not sleep, so the page loads
instantly while the API is still waking and the first query looks like a hung
frontend rather than a cold backend. `plan: starter` in `render.yaml` removes it.

**Preview deployments and CORS.** Vercel gives every preview deployment its own
hostname. `CORS_ORIGINS` lists exact origins, so a preview build loads fine and
then fails every API call in the browser console. Add the preview origins you
care about to the array, or test against the production URL.

**`frontend/Dockerfile` and `frontend/nginx.conf` are not used in production.**
They serve the frontend under `docker-compose` for local work. Vercel runs Vite
and serves the static output directly, so editing the nginx config changes
nothing about the deployed site.

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
| Traceback ends in `asyncpg/connect_utils.py` at `await connected`, with no error class named | An authentication failure masked by asyncpg's `sslmode=prefer` plaintext retry. The credentials are wrong, not the network — TLS had already completed. Check that the user keeps its `.<project-ref>` suffix and that the password is percent-encoded, and add `?sslmode=require` to see the real error. |
| `TypeError: connect() got an unexpected keyword argument 'sslmode'` | A `DATABASE_URL` that bypassed normalization. Confirm it starts with `postgresql://` or `postgresql+asyncpg://`. |
| `prepared statement "__asyncpg_stmt_x__" does not exist` | You are on the transaction pooler (port 6543). Switch to session pooler on 5432. |
| Browser console: blocked by CORS policy | `CORS_ORIGINS` omits the origin the browser is actually sending, or the API was not redeployed after the change. A preview deployment hits this because its hostname is not in the list. |
| API exits at boot with `SettingsError: error parsing value for field "cors_origins"` | A `CORS_ORIGINS` starting with `[` is read as JSON and must use double quotes. Drop the brackets and give a comma-separated list instead. |
| Frontend requests go to `localhost:8000` | The Vercel build predates `VITE_API_BASE_URL`. Redeploy so Vite re-inlines the value; there is nothing to restart. |
| `type "vector" does not exist` when applying the schema | pgvector was not enabled, or it was installed into a schema that is not on the connection's `search_path`. Step 1.2. |
| Uploads succeed, queries return nothing | Documents may still be processing, or `MIN_CHUNK_SIMILARITY` is filtering everything out. Check document status in the UI first. |
