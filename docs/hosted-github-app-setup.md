# Hosted Reviewer Deployment Guide (GitHub App + Render Free Tier)

This guide explains how to turn the Jules-based reviewer into a hosted service that behaves like CodeRabbit:
- Install a **single GitHub App** once and it will monitor every repository you authorize.
- Run the reviewer on **Render's free tier**, so there is no infrastructure cost for a proof of concept.

---

## 0. Prerequisites

| Requirement | Notes |
|-------------|-------|
| GitHub account | You need admin rights on the repositories you want to analyze. |
| Render account | Free tier is enough (https://render.com). |
| Jules API key | Same key used in the POC. |
| Git & Python 3.11+ (local) | For packaging and quick local testing. |

> Tip: Keep a password manager or notes app handy to store the GitHub App ID, Installation ID, Client ID, Client Secret, and Webhook secret.

---

## 1. Prepare a Service Repository

1. **Clone or create a new repository** that will run the hosted reviewer (e.g. `jules-reviewer-service`).
   ```bash
   git clone git@github.com:<your-account>/jules-reviewer-service.git
   cd jules-reviewer-service
   ```
2. Copy over the reusable modules from the POC (`scripts/utils.py`, Jules diff processing logic, etc.).
3. Add a lightweight web server. Example structure using FastAPI:
   ```text
   jules-reviewer-service/
   ├── app/
   │   ├── __init__.py
   │   ├── main.py          # FastAPI entrypoint (POST /github/webhook)
   │   ├── github_auth.py   # JWT + installation token helpers
   │   ├── review_runner.py # wraps compute diff + jules review calls
   │   └── publisher.py     # posts PR/commit comments
   ├── requirements.txt
   └── README.md
   ```
4. Add `requirements.txt` with at least:
   ```txt
   fastapi==0.110.0
   uvicorn==0.29.0
   requests==2.31.0
   PyGithub==2.1.1
   python-dotenv==1.0.0
   ```
5. Create `app/main.py` skeleton:
   ```python
   from fastapi import FastAPI, Header, HTTPException
   from app import github_auth, review_runner

   app = FastAPI()

   @app.post("/github/webhook")
   async def handle_webhook(payload: dict, x_hub_signature_256: str = Header(...)):
       github_auth.verify_signature(payload, x_hub_signature_256)
       event_type = github_auth.get_event_type()
       review_runner.enqueue(payload, event_type)  # or run synchronously for POC
       return {"status": "received"}

   @app.get("/healthz")
   async def healthz():
       return {"ok": True}
   ```
6. Commit the initial files:
   ```bash
   git add .
   git commit -m "Initial hosted reviewer scaffold"
   git push origin main
   ```

---

## 2. Create the GitHub App

1. **Navigate to GitHub App creation page**:
   - Go to https://github.com/settings/apps (personal) or `https://github.com/organizations/<org>/settings/apps` (organization).
   - Click **"New GitHub App"**.
2. **GitHub App configuration**:
   - **App name**: e.g. `Jules Reviewer`
   - **Homepage URL**: link to your repo or documentation.
   - **Webhook URL**: temporary placeholder (e.g. `https://example.com/temp`). You will replace this after deploying to Render.
   - **Webhook secret**: click "Generate" or enter your own strong secret. Save it.
3. **Permissions** (Repository):
   - *Metadata*: Read (auto-selected and required).
   - *Contents*: Read-only.
   - *Pull Requests*: Read & write.
   - *Commit statuses*: Read & write (optional but useful for Checks tab updates).
4. **Subscribe to events**:
   - `Pull request`
   - `Push`
   - `Check suite` (optional)
   - `Installation` (recommended to handle new repos)
5. Click **"Create GitHub App"**.
6. **Generate credentials**:
   - On the app page, click "Generate a private key" → download the `.pem` file (store securely).
   - Note the **App ID** (top-right panel).
   - Under "General" → "Client secrets" → click "Generate a new client secret" → copy/save.
7. **Install the app**:
   - Click "Install App" in the left sidebar.
   - Choose your personal account or organization.
   - Select "All repositories" or pick specific repos.
   - Complete installation (you'll receive an Installation ID later via API calls).

---

## 3. Implement GitHub App Authentication Helpers

1. In your repo, add `app/github_auth.py` to handle JWT & installation tokens, e.g.:
   ```python
   import time
   import jwt
   import requests
   from typing import Dict

   def create_jwt(app_id: str, private_key: str) -> str:
       now = int(time.time())
       payload = {
           "iat": now,
           "exp": now + (10 * 60),
           "iss": app_id,
       }
       return jwt.encode(payload, private_key, algorithm="RS256")

   def get_installation_token(jwt_token: str, installation_id: str) -> str:
       url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
       headers = {
           "Authorization": f"Bearer {jwt_token}",
           "Accept": "application/vnd.github+json",
       }
       response = requests.post(url, headers=headers, timeout=30)
       response.raise_for_status()
       return response.json()["token"]
   ```
2. Implement signature verification using your webhook secret (`X-Hub-Signature-256`) before trusting payloads. Python snippet:
   ```python
   import hmac
   import hashlib

def verify_signature(body: bytes, signature: str, secret: str):
    computed = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
   ```
3. Store the webhook secret in environment variables (`GITHUB_WEBHOOK_SECRET`).

---

## 4. Integrate Jules Review Logic

1. Reuse functions from the POC:
   - Diff computation (adapt to use GitHub API or `git` checkout).
   - Prompt templating and Jules API calls (`JULES_API_KEY`).
   - Posting comments using installation token.
2. Decide on execution model:
   - **Synchronous (simple)**: process review inside the webhook request. Works if reviews finish <60 seconds.
   - **Queued (scalable)**: push payload to a queue (e.g. Upstash Redis free tier) and run a worker on Render (background service).
3. For a pure free setup, synchronous processing is acceptable for small diffs.

---

## 5. Local Dry Run (Optional)

1. Load environment variables via `.env` (never commit real secrets):
   ```env
   GITHUB_APP_ID=123456
   GITHUB_PRIVATE_KEY="""
   -----BEGIN PRIVATE KEY-----
   ...
   -----END PRIVATE KEY-----
   """
   GITHUB_WEBHOOK_SECRET=super-secret
   JULES_API_KEY=your-jules-key
   ```
2. Install deps and run the server locally:
   ```bash
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8000
   ```
3. Use [smee.io](https://smee.io) or [ngrok](https://ngrok.com) to forward GitHub webhooks to your local machine while testing.

---

## 6. Deploy to Render (Free Tier)

1. **Create Render account**: https://render.com → “Get Started for Free”.
2. **Connect GitHub**: authorize Render to access your repositories.
3. **Create a Web Service**:
   - Dashboard → **New** → **Web Service** → select `jules-reviewer-service` repo.
   - **Environment**: `Python`.
   - **Region**: pick the closest region.
   - **Branch**: `main` (or your deployment branch).
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port 10000`
   - **Instance Type**: `Free`.
4. **Set environment variables** (Render dashboard → your service → “Environment” tab → “Add Environment Variable”):
   - `GITHUB_APP_ID`
   - `GITHUB_PRIVATE_KEY` (paste PEM contents; Render supports multiline values)
   - `GITHUB_WEBHOOK_SECRET`
   - `JULES_API_KEY`
   - `REPO_ALLOWLIST` (optional JSON list if you want to restrict repos)
5. Deploy. Render will build and assign a URL like `https://jules-reviewer.onrender.com`.
6. Verify the health endpoint: open `https://<service>.onrender.com/healthz` → expect `{"ok": true}`.

> Render free tier sleeps after 15 minutes of inactivity and cold starts take ~30 seconds. Acceptable for POC.

---

## 7. Wire GitHub App to Render

1. Go back to **GitHub App settings** → "General".
2. Update the **Webhook URL** to your Render endpoint, e.g. `https://jules-reviewer.onrender.com/github/webhook`.
3. Click **"Save changes"**.
4. Trigger a test delivery: in "Advanced" → "Recent deliveries" → "Redeliver" a past event and confirm a 200 response.
5. If you see signature mismatches, double-check the webhook secret and signature verification code.

---

## 8. Verify on a Repository

1. Open or create a PR in a repository where the app is installed.
2. Confirm the webhook reaches Render (Render logs show request).
3. After review completes, check the PR:
   - Inline comments with severity tags.
   - Optional status check or review summary.
4. If nothing appears:
   - Inspect Render logs for stack traces.
   - Check GitHub App "Advanced" → "Recent deliveries" for webhook status.
   - Ensure the installation token has access to that repo (App installed on it).

---

## 9. Optional Enhancements (Still Free)

| Upgrade | How |
|---------|-----|
| Queue + worker | Use Upstash Redis (free) + Render Background Worker (free) to process slow reviews. |
| Persistent logs | Connect to services like Better Stack (free tier). |
| Monitoring | Add endpoints or integrate with Render Health Checks. |
| Config management | Use Render secrets for per-env overrides. |

---

## 10. Maintenance Tips

- Rotate the private key periodically (GitHub App → "Generate new private key").
- Keep dependency versions up to date (monthly check).
- Monitor Jules API usage to stay within any free quota.
- Clean up inactive Render services or sleeping apps to avoid hitting free-tier limits.
- Document installation steps and share the GitHub App install URL with teammates.

---

## Quick Reference

| Task | Where |
|------|-------|
| Create GitHub App | GitHub → Settings → Developer settings → GitHub Apps |
| Generate private key | GitHub App → "Generate a private key" |
| Install app on repos | GitHub App → "Install App" |
| Deploy service | Render dashboard → New Web Service |
| Update webhook URL | GitHub App → General → Webhook |
| View webhook logs | GitHub App → Advanced → Recent deliveries |
| View app logs | Render service → Logs tab |

Once these steps are complete, your Jules-based reviewer behaves like a hosted CodeRabbit alternative: install the GitHub App once and every repo you authorize will automatically receive AI-powered reviews running on Render for free.
