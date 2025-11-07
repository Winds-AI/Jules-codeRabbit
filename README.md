# Jules Code Reviewer – GitHub App + Jules workflow

This service hosts a GitHub App manifest and now delivers fully automated code reviews. When a push or pull request event arrives via webhook, the app verifies the signature, collects GitHub diffs with installation authentication, ships them to the [Jules API](https://developers.google.com/jules/api), and posts inline comments plus a review summary back to GitHub.

## What you get

- Hosted `/github/manifest` and `/github/register` endpoints to bootstrap per-user GitHub Apps.
- HMAC validated `/webhook` endpoint with delivery de-duplication.
- Async in-process job queue that fetches diffs, calls Jules, and publishes results.
- Inline review comments for both PRs and single-commit pushes, plus a severity-weighted summary comment.

## Prerequisites

- Python 3.11+
- Network access to `api.github.com` (or your GitHub Enterprise host) and `jules.googleapis.com`
- GitHub App credentials created via the manifest flow
- A Jules API key generated from the Jules console

## Required environment variables

Set these before starting the service (locally you can create a `.env` file; on Render/other hosts use environment configuration):

- `SERVICE_BASE_URL` – Public HTTPS URL of this service
- `GITHUB_APP_ID` – Numeric ID from the manifest conversion page
- `GITHUB_PRIVATE_KEY` – PEM contents of the GitHub App private key
- `GITHUB_WEBHOOK_SECRET` – Secret used to sign webhooks
- `JULES_API_KEY` – Jules API key passed via `X-Goog-Api-Key`
- `GITHUB_API_BASE_URL` *(optional)* – Override for GitHub Enterprise instances
- `MANIFEST_PUBLIC` *(optional)* – Set to `true` if the manifest endpoint is exposed publicly

## Local development

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

While running locally, set `SERVICE_BASE_URL` to a tunnel (e.g., `ngrok`) so GitHub can reach your webhook.

## Deployment checklist

1. Visit `/github/manifest` and create your GitHub App using the generated manifest.
2. Copy the credentials from `/github/register?code=...` into your host’s environment settings.
3. Add `JULES_API_KEY` from the Jules console (Settings → API Keys).
4. Deploy the FastAPI app and confirm `/health` returns `200`.
5. Install your GitHub App on the target repositories and push a commit to trigger the review pipeline.

## Endpoints

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/github/manifest` | GET | Generates a GitHub App manifest based on `SERVICE_BASE_URL`. |
| `/github/register` | GET | Exchanges the manifest code for app credentials and renders copy helpers. |
| `/webhook` | POST | Verifies webhook signatures, dedupes deliveries, and enqueues review jobs. |
| `/setup` | GET | Human-readable setup guidance including env var reminders. |
| `/health` | GET | Service and dependency metadata for probes. |

## Operational notes

- Webhook signatures use `X-Hub-Signature-256` HMAC verification and the delivery ID cache prevents double-processing within one hour.
- GitHub API access uses short-lived installation tokens minted from the app’s private key; tokens are cached per installation.
- The review worker sends diffs to Jules with explicit instructions to return JSON `{summary, comments[]}`. Responses are parsed and converted into PR reviews or commit comments.
- Comment severity is echoed in each inline body and summarized once per review.
- Commit reviews target the push `after` SHA; summaries post as top-level commit comments.
- Errors from GitHub or Jules are logged and the associated job is skipped (future improvements could add retries/backoff).

## Security checklist

- Secrets are never persisted—everything is sourced from environment variables at runtime.
- Always deploy behind HTTPS and keep `SERVICE_BASE_URL` updated to avoid signature mismatches.
- Rotate the GitHub webhook secret and Jules API key periodically; restart the service so cached tokens refresh.
