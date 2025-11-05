---

# 1 — Top-level goals (brief)

* Provide a small, deployable FastAPI service that:

  1. Serves a GitHub App manifest (`/github/manifest`) so users can create their own GitHub App.
  2. Handles manifest conversion callback (`/github/register`) to receive the user’s App credentials.
  3. Receives and verifies GitHub webhooks at `/webhook`.
  4. Enqueues jobs for processing pushes (fetch diffs, call Jules with user-supplied API key, and post comments).
  5. Exposes a setup UI where users view & copy their App credentials and paste their Jules API key.
  6. Provides a small admin/debug UI (optional) for local testing.
* Package and deploy to Render (web service + optional background worker).

---

# 2 — Repo layout (files & folders)

```
codereviewbot/
├── README.md
├── render.yaml                 # Render service configs (optional)
├── pyproject.toml / requirements.txt
├── .env.template               # example env vars
├── src/
│   ├── main.py                 # FastAPI app entry
│   ├── config.py               # config loader (env)
│   ├── manifest.py             # manifest generation endpoint
│   ├── register.py             # manifest conversion endpoint
│   ├── webhook.py              # webhook receiver & validator
│   ├── worker.py               # background worker (consumer)
│   ├── github_client.py        # GitHub App auth & API helpers
│   ├── jules_client.py         # Jules API integration wrapper
│   ├── queue/
│   │   ├── queue_interface.py  # abstract queue interface
│   │   └── redis_queue.py      # Redis implementation (or in-memory for dev)
│   ├── models/
│   │   └── schemas.py          # pydantic request/response models
│   ├── templates/              # Jinja2 templates for setup pages
│   │   ├── success.html
│   │   └── setup.html
│   └── utils/
│       ├── logging.py
│       └── security.py         # signature verification helpers
├── tests/
│   ├── test_manifest.py
│   ├── test_webhook_signature.py
│   └── test_jules_client.py
└── docs/
    ├── architecture.md
    └── onboarding.md
```

---

# 3 — Core environment variables (from `.env.template`)

Provide these as Render environment variables or local `.env` for development.

```
# For the manifest-hosting "manager" app (optional)
SERVICE_BASE_URL=https://your-setup-service.onrender.com

# If you plan to run this central manifest service (not required for user self-hosting)
MANIFEST_PUBLIC=true

# App-run-time (not the per-user GitHub App)
APP_SECRET_KEY=some_random_secret_for_session_cookie

# Redis / queue
REDIS_URL=redis://localhost:6379/0

# Storage / DB for storing per-installation data (if you provide central storage)
DATABASE_URL=sqlite:///./dev.db  # for prototype, Postgres for production

# Optional email, Sentry, etc.
```

> Note: Each user who uses the manifest flow receives their own `pem`, `webhook_secret`, `app_id`, etc. Those values should be stored by the user in their own Render environment or in the user's deployment. If you choose to centrally store user credentials (not recommended), treat them as secrets and encrypt at rest.

---

# 4 — Endpoints to implement (detailed)

## 4.1 `/github/manifest` — GET

* Returns JSON manifest used for GitHub App creation.
* Template fields must include placeholders for `url`, `hook_attributes.url`, `redirect_url`.
* Implementation notes:

  * Use `SERVICE_BASE_URL` to populate `YOUR_RENDER_URL` dynamically.
  * `default_permissions` should be:

    * `contents: read`
    * `pull_requests: write`
    * `metadata: read`
    * `issues: write` (optional)
    * `commit_statuses: write` (optional)
  * `default_events`: `["push", "pull_request", "installation"]`
* Security: no sensitive data in the manifest.

## 4.2 `/github/register` — GET

* Called by GitHub with `?code=...` after user confirms app creation.
* Implementation steps:

  1. Read `code` parameter.
  2. POST to `https://api.github.com/app-manifests/{code}/conversions` with `Accept: application/vnd.github+json`.
  3. Receive JSON: `{id, slug, pem, webhook_secret, client_id, client_secret, html_url, ...}`.
  4. Present credentials in an HTML page for the user to copy or provide a downloadable `.pem`.
  5. Optionally implement an automated helper that, if the user is logged in (or has provided deployment credentials), saves these to their deployed instance (advanced, optional).
* Security: do not persist `pem` unless you implement secure secret storage. If you persist, encrypt at rest.

## 4.3 `/webhook` — POST

* Receives GitHub events.
* Steps:

  1. Verify signature: `X-Hub-Signature-256` header with `WEBHOOK_SECRET` belonging to the *installation* (NOT the manifest-host service secret). If you hold this centrally, look it up by `installation_id` in payload.
  2. Parse event type: `X-GitHub-Event`.
  3. Handle only `push` and optionally `pull_request` events. For `push`:

     * Enqueue a job with `installation_id`, `repo`, `pusher`, `commit_ids`, `ref`, etc.
  4. Respond `200` quickly (webhook should return fast). **Do not** perform Jules calls inline.
* Idempotency: use event delivery `X-GitHub-Delivery` to dedupe.

## 4.4 Worker (background) — `worker.py`

* Consumes queue jobs.
* For each job:

  1. Use GitHub App auth to generate an installation access token for `installation_id`.

     * Steps (must verify current GitHub docs):

       * Create a JWT signed with the private key for the *app* (if app is per-user, use their stored PEM).
       * Exchange JWT for installation token via `POST /app/installations/:installation_id/access_tokens`.
  2. Fetch commit diffs:

     * Use GitHub API: `GET /repos/{owner}/{repo}/commits/{sha}` or `GET /repos/{owner}/{repo}/compare/{base}...{head}` to get diffs.
     * If `pull_request`, use PR files list: `GET /repos/{owner}/{repo}/pulls/{number}/files`.
  3. Prepare payload for Jules:

     * Extract file diffs (patch), commit message, committer name/email, and minimal surrounding context for each snippet.
     * Respect file size/line limits — truncate or sample large files.
  4. Call Jules API (per-user key) with proper instruction prompt to identify bugs/security issues and return comments with file, line, and message.

     * Implement robust error handling, retry logic, timeout, and rate-limiting.
  5. Post comments via GitHub API:

     * For PRs: Use Review Comments API `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews` or create review comments inline `POST /repos/{owner}/{repo}/pulls/{pull_number}/comments`.
     * For commit comments: `POST /repos/{owner}/{repo}/commits/{commit_sha}/comments`.
  6. Mark job done; optionally persist analysis result.

---

# 5 — GitHub App auth (important — agent must check latest docs)

**Agent instruction:** *Look up the current GitHub App authentication flow and JWT signing procedures before coding.* Implementation must:

* Build a JWT signed by the GitHub App private key (RS256).
* Exchange JWT for an installation access token (`POST /app/installations/:installation_id/access_tokens`).
* Use the installation token for repo API calls.

> NOTE: GitHub’s API details and header formats evolve — the agent must consult the GitHub App docs at implementation time to match latest endpoints and required `Accept` headers.

---

# 6 — Jules API integration (agent must look up latest docs)

**Agent instruction:** *Look up the latest Jules API docs and required request structure — use the official SDK or HTTP format as documented.* Key points to implement:

* Jules API call must use the **user-provided Jules API key** (never your central key).
* Provide instructions/context in the request telling Jules to:

  * Find bugs and security issues in the code diff.
  * Return results with file path, start_line, end_line, comment_text, severity.
* Implement retries with exponential backoff and honor Jules’ rate limits.
* Sanitize code snippets if the user asks for privacy (optional setting).

---

# 7 — Queue & worker details

* Use Redis + RQ, or Redis + custom async worker, or Celery (choose one).
* For a prototype:

  * Provide a simple in-memory queue implementation that works locally.
  * Provide a Redis-backed queue implementation for production (REDIS_URL).
* Worker behavior:

  * Concurrent worker processes (1 by default, configurable).
  * Job timeout and retry policy.
  * Logging for failures and audit.

---

# 8 — UI pages (templates)

## A. Setup page (`/setup`) — optional but recommended

* Purpose: after the user creates their app, show steps to deploy.
* Contents:

  * Help text: “Copy these values into your Render deployment environment: GITHUB_APP_ID, GITHUB_PRIVATE_KEY (pem), GITHUB_WEBHOOK_SECRET, JULES_API_KEY”
  * Provide a downloadable PEM paste area or `.pem` file link (from the `register` response).
  * Button to copy all env vars to clipboard.

## B. Manifest conversion success (`/github/register`) — required

* Show the JSON returned (App ID, webhook secret) and buttons:

  * “Download PEM”
  * “Copy env vars”
  * “Open Deploy Guide” (link to `docs/onboarding.md`)

## C. Health & Debug (`/health`, `/debug`) — optional

* `GET /health`: liveness probe for Render.
* `GET /debug`: show last few webhook events (only in dev mode).

---

# 9 — Security & best practices

* **Secrets**:

  * Never commit private key PEMs or Jules keys.
  * Use Render environment variables to store secrets.
  * If storing user secrets centrally, encrypt at rest (use KMS).
* **Webhook signature verification**:

  * Use HMAC SHA256 and compare with constant-time comparison.
* **Rate limiting & quotas**:

  * Per-installation rate limiting to avoid overuse of Jules credits.
  * Provide a user-level throttle (e.g., 1 analysis / minute per repo by default).
* **Data minimization**:

  * Send only necessary context to Jules, not entire repo history.
* **Idempotency**:

  * Use `X-GitHub-Delivery` for dedupe and job dedupe keys.
* **Logging**:

  * Redact secrets in logs.
  * Keep audit trail of analysis events.

---

# 10 — Tests & local dev

* Include unit tests for:

  * Manifest response structure.
  * Signature verification.
  * Job enqueue + worker processing (mock GitHub & Jules).
* Provide a `docker-compose.yml` for dev (FastAPI + Redis).
* Provide a `Makefile` with commands:

  * `make run`
  * `make test`
  * `make lint`

---

# 11 — CI / CD

* GitHub Actions (basic):

  * `lint` (flake8/ruff)
  * `test`
  * `build` (optional)
* Optionally provide a `render.yaml` that maps to Render services:

  * One web service for the manifest + UI.
  * One background worker service for processing (can be same service for prototyping).

---

# 12 — Render deployment notes (quick)

* For each user, instruct them to:

  1. Deploy the repo to Render (public Git repo).
  2. In Render service settings, set env vars:

     * `GITHUB_APP_ID`
     * `GITHUB_PRIVATE_KEY` (multi-line PEM)
     * `GITHUB_WEBHOOK_SECRET`
     * `JULES_API_KEY`
     * `REDIS_URL` (if using Redis queue)
     * `SERVICE_BASE_URL` = Render service URL
  3. Add `WEB_CONCURRENCY` / worker config if worker is separate.
  4. Set up health check path to `/health`.
* **Caveat**: Render free tier may sleep — recommend paid plan for production reliability.

---

# 13 — Onboarding docs & README contents (what to write)

* A step-by-step **Getting Started**:

  * Deploy repo to Render.
  * Create GitHub App via manifest link:

    ```
    https://github.com/settings/apps/new?manifest=https://YOUR_SETUP_SERVICE_URL/github/manifest
    ```
  * On `register` page, copy credentials into Render env.
  * Install GitHub App on your repo.
  * Add `JULES_API_KEY` via UI.
  * Push a commit to see the bot work.
* Troubleshooting tips:

  * Webhook signature failures.
  * Rate-limits & Jules errors.
* Security & privacy notes.

---

# 14 — Additional implementation instructions for the AI agent (explicit)

1. **Before coding any GitHub integration**: fetch and read the latest GitHub App docs:

   * GitHub Apps authentication (JWT issuance and installation access tokens).
   * Current recommended `Accept` headers for the conversions endpoint.
2. **Before coding Jules integration**: fetch the latest Jules API docs to confirm:

   * Endpoint(s), request/response structure, rate limiting, authentication header name, and any SDK availability.
3. **Before coding deployment**: fetch Render docs for:

   * Multi-line env var handling (PEM), background workers, and `render.yaml` schema.
4. Use small, testable commits and add unit tests for security-critical code (signature verification and token exchange).
5. Implement feature flags/config toggles for “dev_mode” vs “production” that control logging and whether secrets are persisted.

---

# 15 — Minimal manifest JSON (exact content to serve)

```json
{
  "name": "CodeReviewBot",
  "url": "https://YOUR_RENDER_URL",
  "hook_attributes": {
    "url": "https://YOUR_RENDER_URL/webhook",
    "active": true
  },
  "redirect_url": "https://YOUR_RENDER_URL/github/register",
  "callback_url": "https://YOUR_RENDER_URL/callback",
  "public": true,
  "default_permissions": {
    "contents": "read",
    "pull_requests": "write",
    "issues": "write",
    "metadata": "read",
    "commit_statuses": "write"
  },
  "default_events": [
    "push",
    "pull_request",
    "installation"
  ]
}
```

> Agent: replace `YOUR_RENDER_URL` dynamically from env var `SERVICE_BASE_URL`.

---

# 16 — Example minimal FastAPI skeleton (pseudocode — agent should implement actual code and tests)

```python
# main.py (simplified)
from fastapi import FastAPI
from src.manifest import router as manifest_router
from src.register import router as register_router
from src.webhook import router as webhook_router

app = FastAPI()
app.include_router(manifest_router, prefix="/github")
app.include_router(register_router, prefix="/github")
app.include_router(webhook_router, prefix="/")

@app.get("/health")
def health():
    return {"status": "ok"}
```

---

# 17 — Next moves I can do for you right now

Tell me which of the following you want me to produce immediately (I’ll generate it in this chat):

* A ready-to-deploy **FastAPI skeleton** with the exact file contents (manifest endpoint, register endpoint, webhook stub, README, requirements).
* A `docker-compose.yml` and `Makefile` for development.
* A complete `docs/onboarding.md` and sample `render.yaml`.
* Or all of the above as a single packaged repo scaffold.