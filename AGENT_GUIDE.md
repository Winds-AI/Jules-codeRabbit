# 🧠 `AGENT_GUIDE.md` — CodeReviewBot AI Development Instructions

> 📄 Purpose:
> This document gives precise instructions for any AI coding agent (e.g. Cursor, Windsurf, Copilot Workspace) contributing to this repository.
> The goal is to ensure code generation aligns with current APIs, repo structure, and secure best practices.

---

## ⚙️ Project Context

* This repo implements **CodeReviewBot**, a self-hostable GitHub App similar to CodeRabbit.
* The bot:

  * Listens to **GitHub push** and **pull_request** events.
  * Sends **commit diffs**, **commit message**, and **committer name** to the **Google Jules API** for automated review.
  * Posts review comments on GitHub via the **GitHub REST API**.
* Each user:

  * Creates **their own GitHub App instance** via a **Manifest Flow** served by this backend.
  * Deploys this app on **Render**.
  * Supplies their own **Google Jules API key** (to manage credits).
* Backend: **FastAPI (Python 3.11+)**
* Queue: Redis or local async worker
* Deployment: Render (web service + optional worker)

---

## 🧩 Key Responsibilities for the AI Agent

### ✅ Always Do:

1. **Look up latest official documentation before coding external integrations:**

   * **GitHub Apps**

     * Authentication (JWT + installation tokens)
     * Webhook validation
     * Endpoints for:

       * Manifest conversion: `POST /app-manifests/{code}/conversions`
       * Posting PR comments: `/repos/{owner}/{repo}/pulls/{number}/comments`
       * Posting commit comments: `/repos/{owner}/{repo}/commits/{sha}/comments`
   * **Google Jules API**

     * Verify endpoints, authentication headers, payload structure, and limits.
   * **Render**

     * Check how Render handles environment variables, background workers, and sleeping behavior in free plans.
   * **Redis (or chosen queue lib)**

     * Follow the latest version’s connection and worker setup.

2. **Implement all API clients modularly.**
   Keep GitHub and Jules integrations isolated (`github_client.py`, `jules_client.py`).

3. **Document every new function** (docstring + purpose).
   Use type hints and Pydantic models for input/output schemas.

4. **Handle all secrets and tokens via environment variables only.**
   Never hardcode private keys, secrets, or test tokens.

5. **Write clean async code.**
   Use `async`/`await` with FastAPI and `httpx` for I/O.

6. **Test webhook signature verification** using HMAC SHA256 and compare safely (constant-time).

7. **Add rate limits & error handling** for Jules API (429, 500, etc.).

8. **Use retry logic** with exponential backoff for all network calls.

9. **Follow repo structure exactly** as defined in `docs/architecture.md`.
   Never flatten or rename directories unless explicitly instructed.

10. **Keep the service stateless** except for minimal DB usage (user installations, job queue metadata).

---

## ❌ Never Do:

* ❌ Don’t call unverified third-party APIs.
* ❌ Don’t log secrets, raw private keys, or Jules API responses.
* ❌ Don’t hardcode URLs or credentials in source code.
* ❌ Don’t delete or rewrite files in `/docs`, `/templates`, or `/tests` without explicit instruction.
* ❌ Don’t change permissions or events in the manifest unless GitHub’s docs indicate required updates.

---

## 🧱 Implementation Standards

### Code style

* Follow **PEP 8** + type hints (`mypy` compatible).
* Use `black` or `ruff` for formatting (add config in `pyproject.toml`).

### Testing

* Use `pytest`.
* Mock GitHub and Jules APIs in unit tests.
* Include tests for:

  * Manifest JSON structure validity.
  * Webhook signature verification.
  * Queue job enqueue/dequeue.
  * Posting of comments (mocked).
  * Jules API response parsing.

### Logging

* Use Python’s `logging` module.
* Sanitize logs (never print payloads or credentials).
* Include request IDs (GitHub `X-GitHub-Delivery`).

### Error Handling

* Catch all exceptions in worker loops.
* Respond `200` to GitHub even on failures (log errors internally).
* Provide `retry_count` and exponential backoff in job metadata.

---

## 🧩 Manifest and Setup Flow Notes

* The manifest JSON is served from `/github/manifest`.
* The redirect URL (`/github/register`) must:

  * Exchange `code` for credentials using GitHub’s conversion endpoint.
  * Render HTML success page with:

    * App ID
    * Webhook secret
    * Private key PEM download
    * Example Render `.env` values
* Never store private key PEM unless explicitly allowed.
  Show it once and discard.

---

## ⚙️ Queue / Worker Rules

* Use Redis or async task queue.
* Each job includes:

  * `installation_id`
  * `repository_full_name`
  * `head_commit`
  * `user_jules_key`
* Worker responsibilities:

  * Generate GitHub installation token.
  * Fetch commit diff.
  * Send to Jules.
  * Post comments.
* Worker must be **idempotent** (skip duplicate `X-GitHub-Delivery`).

---

## 🔐 Security Checklist (AI agent must maintain)

| Area           | Rule                                         |
| -------------- | -------------------------------------------- |
| GitHub webhook | Verify signature with user’s stored secret   |
| Private keys   | Store in `.env` only; multi-line PEM support |
| Jules keys     | User-supplied and encrypted if stored        |
| HTTPS          | Always use HTTPS URLs in manifest            |
| Logs           | No sensitive fields                          |

---

## 🧠 Integration Notes (agent reminders)

### GitHub

* Use `PyJWT` for JWT signing (`RS256`).
* Use `httpx` or `requests` with timeouts.
* Add `User-Agent: CodeReviewBot` to all API calls.
* Retry 3x with exponential backoff for transient 5xx.

### Jules API

* Auth header typically `Authorization: Bearer <key>`.
* Provide structured payload:

  ```json
  {
    "instruction": "Find bugs and security issues in the following diff",
    "diff": "...",
    "commit_message": "...",
    "committer": "...",
    "language": "auto"
  }
  ```
* Expect structured response or parse text for comment entries.

---

## 🧰 Tooling & Dependency Notes

* Use `fastapi`, `uvicorn`, `httpx`, `pydantic`, `redis`, `pytest`, `pyjwt`.
* Use latest stable versions (agent should look up latest PyPI releases).

---

## 📦 Deployment Rules (Render)

* Use `requirements.txt` or `pyproject.toml`.
* Web service command: `uvicorn src.main:app --host 0.0.0.0 --port 10000`.
* Optional worker: `python -m src.worker`.
* Healthcheck path: `/health`.
* Render’s free plan sleeps — warn users if used for production.

---

## 🚨 Final Agent Reminder

Before writing or modifying any code:

* ✅ Recheck the official docs for any API you integrate.
* ✅ Include unit tests for all new endpoints.
* ✅ Respect repo folder structure.
* ✅ Keep code modular and documented.
* ✅ Confirm API request formats with live examples before deployment.

---

### Example Footer (optional)

```text
This AGENT_GUIDE.md defines the authoritative coding policy for CodeReviewBot.
All automated agents must follow these rules before generating or modifying code.
Violations (like hardcoding secrets or skipping tests) will be reverted automatically.
```

---