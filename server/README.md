# Jules Code Review - Webhook Server

Flask server that receives GitHub webhooks and performs code reviews using Jules API.

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in:
- `GITHUB_APP_ID` - From GitHub App settings
- `GITHUB_PRIVATE_KEY` - Download from GitHub App
- `GITHUB_WEBHOOK_SECRET` - Set in GitHub App webhook settings
- `JULES_API_KEY` - Your Jules/Gemini API key

### 3. Run Locally
```bash
python app.py
```

Server runs on `http://localhost:5000`

## Deploy to Render

1. Push code to GitHub
2. Connect repository to Render
3. Render will auto-detect `render.yaml`
4. Add environment variables in Render dashboard
5. Deploy!

## Endpoints

- `POST /webhook` - GitHub webhook receiver
- `GET /health` - Health check
- `GET /` - Server info

## GitHub App Setup

1. Create GitHub App at: `https://github.com/settings/apps/new`
2. Set webhook URL: `https://your-app.onrender.com/webhook`
3. Generate webhook secret
4. Set permissions:
   - Repository contents: Read
   - Pull requests: Read & Write
   - Checks: Write
5. Subscribe to events:
   - Pull request
   - Push
6. Download private key
7. Install app on repositories

## Testing

Use ngrok for local testing:
```bash
ngrok http 5000
# Use ngrok URL as webhook URL
```

## Architecture

```
GitHub → Webhook → app.py → review_service.py
                              ├─ github_client.py (fetch diff)
                              ├─ jules_client.py (review code)
                              └─ github_client.py (post comments)
```
