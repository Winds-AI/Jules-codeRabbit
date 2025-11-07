 # AGENTS.md

 ## Project overview

 This repository implements a self-hostable GitHub App service that performs automated code reviews using FastAPI and the Google Jules API. It exposes endpoints to bootstrap a per-user GitHub App via a manifest flow, validates GitHub webhooks, collects diffs with installation tokens, sends them to Jules, and posts inline comments and a summary back to GitHub.

 Key features:
 - Hosted `/github/manifest` and `/github/register` endpoints for GitHub App setup
 - HMAC-validated `/webhook` endpoint with delivery de-duplication
 - Async in-process job queue to fetch diffs, call Jules, and publish comments
 - Inline review comments for PRs and single-commit pushes, plus a severity-weighted summary
 - Health endpoint for probes and basic service info

 Reference implementation details are in `README.md` and the `src/` directory.

 ## Setup commands

 - Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .\.venv\Scripts\Activate.ps1
   ```

 - Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

 - Start the dev server (auto-reload):
   ```bash
   python run.py
   # or
   uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
   ```

 - Health check (once running):
   ```bash
   curl http://localhost:8000/health
   ```

 - For GitHub webhook testing, expose a public tunnel and set `SERVICE_BASE_URL` accordingly (e.g., ngrok):
   ```bash
   ngrok http 8000
   export SERVICE_BASE_URL="https://<your-ngrok-subdomain>.ngrok.io"
   ```

 ## Required environment variables

 Set these before starting the service (use a local `.env` file for development, production hosts should configure their environment securely):

 - `SERVICE_BASE_URL` – Public HTTPS URL of this service
 - `GITHUB_APP_ID` – Numeric GitHub App ID from manifest conversion
 - `GITHUB_PRIVATE_KEY` – PEM contents of the GitHub App private key
 - `GITHUB_WEBHOOK_SECRET` – Secret used to sign webhooks
 - `JULES_API_KEY` – Jules API key (sent via `X-Goog-Api-Key` or appropriate auth header)
 - `GITHUB_API_BASE_URL` (optional) – Override for GitHub Enterprise
 - `MANIFEST_PUBLIC` (optional) – `true` to enforce public HTTPS for the manifest flow

 Notes:
 - Configuration model lives in `src/config.py`.
 - The app will raise an error on startup if critical variables are missing.

 ## Endpoints

 | Endpoint | Method | Purpose |
 | --- | --- | --- |
 | `/github/manifest` | GET | Generates a GitHub App manifest based on `SERVICE_BASE_URL`.
 | `/github/register` | GET | Exchanges the manifest code for app credentials and renders copy helpers.
 | `/webhook` | POST | Verifies webhook signatures, dedupes deliveries, and enqueues review jobs.
 | `/setup` | GET | Human-readable setup guidance including env var reminders.
 | `/health` | GET | Service and dependency metadata for probes.
 | `/` | GET | Simple ping response (`pong`).

 ## Development workflow

 - Run locally with auto-reload via `python run.py` or `uvicorn`.
 - Set `SERVICE_BASE_URL` to a public URL when receiving GitHub webhooks (e.g., via ngrok).
 - The queue worker is configured on FastAPI startup; jobs are enqueued by `/webhook`.
 - Delivery de-duplication is enforced using in-memory delivery ID caching.

 ## Code style

 - Python 3.11+
 - Follow PEP 8 and use type hints throughout (Pydantic models in `src/models` and `src/queue/models`).
 - Keep modules small and responsibilities clear; prefer async I/O with `httpx` and FastAPI.
 - Security and error handling: never log secrets or raw private keys; use constant-time signature checks.

 ## Testing instructions

 - Unit tests (if present) should be run with:
   ```bash
   pytest -q
   ```
 - Focused tests:
   ```bash
   pytest -q -k "<pattern>"
   ```
 - Suggested coverage areas:
   - Manifest JSON structure
   - Webhook signature verification
   - Job enqueue/dequeue behavior
   - Jules API response parsing
   - Posting of comments (mock GitHub and Jules calls)

 ## PR instructions

 - Ensure local checks pass before pushing:
   - Server boots and `/health` returns `200`
   - Tests (if present) pass locally
 - Commit and PR title guidelines:
   - Use clear, action-oriented titles (e.g., "Add webhook signature verification")
   - Include brief rationale and any operational changes (env vars, migrations)

 ## Deployment

 - Reference `render.yaml` for deployment configuration:
   - Build command: `pip install --upgrade pip && pip install -r requirements.txt`
   - Start command: `uvicorn src.main:app --host 0.0.0.0 --port 10000`
   - Health check path: `/health`
   - `SERVICE_BASE_URL` typically set to `${RENDER_EXTERNAL_URL}`
 - Post-deploy checklist:
   1. Visit `/github/manifest` to create your GitHub App.
   2. Complete `/github/register?code=...` and store credentials in host env.
   3. Set `JULES_API_KEY` from the Jules console.
   4. Install your GitHub App to target repositories.
   5. Push a commit to trigger the review pipeline.

 ## Security considerations

 - Secrets are provided only via environment variables; never commit to source control.
 - Always use HTTPS URLs for public endpoints and webhook callbacks.
 - Rotate `GITHUB_WEBHOOK_SECRET` and `JULES_API_KEY` periodically.
 - Do not log sensitive payloads or credentials; sanitize logs.

 ## Agent-specific tips

 - When editing code in `src/`, respect module boundaries (`github_client.py`, `jules_client.py`, `services/`, `queue/`).
 - For new external integrations, verify request/response formats in official docs and add unit tests.
 - Keep the service stateless; store only minimal metadata if absolutely necessary.

 ---

 This AGENTS.md is intended as an agent-focused companion to `README.md`. For human-friendly setup and context, see `README.md`.

