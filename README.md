# Jules Code Reviewer – GitHub App Setup

This project currently focuses on providing a self-serve flow for creating a GitHub App via a hosted manifest. Jules diff analysis and automated webhook handling are intentionally out of scope for now.

## Prerequisites

- Python 3.11+
- `SERVICE_BASE_URL` environment variable pointing to the deployed FastAPI service (must be HTTPS in production)
- Network access to the GitHub REST API

## Quick Start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Export the required environment variable for local development:
   ```bash
   export SERVICE_BASE_URL="https://your-public-service"
   ```
3. Run the FastAPI app locally:
   ```bash
   uvicorn src.main:app --reload
   ```
4. Visit `http://localhost:8000/github/manifest` (or your deployed URL) and copy the JSON into the GitHub App manifest form.
5. After GitHub redirects back to `/github/register?code=...`, capture the credentials shown on the success page. **We do not store any secrets.**
6. Follow the `/setup` page for a deployment checklist.

## Endpoints

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/github/manifest` | GET | Returns manifest JSON with URLs derived from `SERVICE_BASE_URL`. |
| `/github/register` | GET | Exchanges the manifest code for credentials and renders a one-time HTML page with copy helpers. |
| `/setup` | GET | Static instructions enumerating the manual steps required after registration. |
| `/health` | GET | Returns service status and version metadata. |

## Testing

Run the unit tests to verify manifest and register behavior:
```bash
pytest
```

## Security Notes

- Credentials displayed on `/github/register` are never persisted. Users must copy and store them immediately.
- `SERVICE_BASE_URL` must use HTTPS when the manifest is public.
- Webhook processing and Jules integrations are currently inactive, so no GitHub events are handled.
