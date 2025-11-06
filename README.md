# Jules Code Reviewer – GitHub App Setup

This project currently focuses on providing a self-serve flow for creating a GitHub App via a hosted manifest. Jules diff analysis and automated webhook handling are intentionally out of scope for now.

## Prerequisites

- Python 3.11+
- `SERVICE_BASE_URL` environment variable pointing to the deployed FastAPI service (must be HTTPS in production)
- Network access to the GitHub REST API

## Quick Start

1. Create a virtual environment:
   ```bash
   python -m venv .venv
   ```
2. Activate the virtual environment:
   - **Windows (PowerShell):**
     ```powershell
     .\.venv\Scripts\Activate.ps1
     ```
   - **macOS / Linux (bash):**
     ```bash
     source .venv/bin/activate
     ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Export the required environment variable for local development:
   ```bash
   export SERVICE_BASE_URL="https://your-public-service"
   ```
5. Run the FastAPI app locally:
   ```bash
   uvicorn src.main:app --reload
   ```
6. Launch the automatic GitHub App creation flow:

   [![Create GitHub App](https://img.shields.io/badge/Create%20GitHub%20App-blue?style=for-the-badge)](https://github.com/settings/apps/new?manifest=%7B%22name%22%3A%22CodeReviewBot%22%2C%22description%22%3A%22Automated%20GitHub%20pull%20request%20reviews%20powered%20by%20Google%20Jules.%22%2C%22url%22%3A%22https%3A%2F%2Fjules-coderabbit.onrender.com%22%2C%22hook_attributes%22%3A%7B%22url%22%3A%22https%3A%2F%2Fjules-coderabbit.onrender.com%2Fgithub%2Fwebhook%22%2C%22active%22%3Atrue%7D%2C%22redirect_url%22%3A%22https%3A%2F%2Fjules-coderabbit.onrender.com%2Fgithub%2Fregister%22%2C%22callback_urls%22%3A%5B%22https%3A%2F%2Fjules-coderabbit.onrender.com%2Fcallback%22%5D%2C%22public%22%3Afalse%2C%22default_permissions%22%3A%7B%22contents%22%3A%22read%22%2C%22metadata%22%3A%22read%22%2C%22pull_requests%22%3A%22write%22%2C%22issues%22%3A%22write%22%2C%22commit_statuses%22%3A%22write%22%7D%2C%22default_events%22%3A%5B%22push%22%2C%22pull_request%22%5D%2C%22setup_url%22%3A%22https%3A%2F%2Fjules-coderabbit.onrender.com%2Fsetup%22%7D)
7. After GitHub redirects back to `/github/register?code=...`, capture the credentials shown on the success page. **We do not store any secrets.**
8. Follow the `/setup` page for a deployment checklist.

## Endpoints

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/github/manifest` | GET | Returns manifest JSON with URLs derived from `SERVICE_BASE_URL`. |
| `/github/register` | GET | Exchanges the manifest code for credentials and renders a one-time HTML page with copy helpers. |
| `/setup` | GET | Static instructions enumerating the manual steps required after registration. |
| `/health` | GET | Returns service status and version metadata. |

## Security Notes

- Credentials displayed on `/github/register` are never persisted. Users must copy and store them immediately.
- `SERVICE_BASE_URL` must use HTTPS when the manifest is public.
- Webhook processing and Jules integrations are currently inactive, so no GitHub events are handled.
