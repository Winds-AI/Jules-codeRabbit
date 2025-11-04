# GitHub App Architecture: Jules Code Reviewer

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                           GITHUB                                     │
│                                                                       │
│  ┌──────────┐      ┌──────────┐      ┌──────────┐                  │
│  │ User Repo│◄────►│ GitHub   │◄────►│ Installed│                  │
│  │          │      │ API      │      │ Repos    │                  │
│  └────┬─────┘      └────┬─────┘      └──────────┘                  │
│       │                 │                                            │
│       │ Commit/PR       │ Webhook                                    │
│       ▼                 ▼                                            │
└───────┼─────────────────┼────────────────────────────────────────────┘
        │                 │
        │                 │ POST /webhook
        │                 │ {event: push/pull_request}
        │                 │
        │                 ▼
┌───────┼─────────────────────────────────────────────────────────────┐
│       │            YOUR SERVER (Jules App)                           │
│       │                                                               │
│  ┌────▼─────────────────────────────────────────────────┐           │
│  │  Webhook Handler (Flask/FastAPI/Express)              │           │
│  │  • Verify GitHub signature                            │           │
│  │  • Parse event payload                                │           │
│  │  • Extract PR/commit metadata                         │           │
│  └────┬──────────────────────────────────────────────────┘           │
│       │                                                               │
│       ▼                                                               │
│  ┌─────────────────────────────────────────────────────┐            │
│  │  Diff Service                                        │            │
│  │  • Fetch PR/commit diff via GitHub API              │            │
│  │  • Parse unified diff format                         │            │
│  │  • Extract file changes                              │            │
│  └────┬─────────────────────────────────────────────────┘            │
│       │                                                               │
│       ▼                                                               │
│  ┌─────────────────────────────────────────────────────┐            │
│  │  Jules Review Service                                │            │
│  │  • Load prompt template                              │            │
│  │  • Insert diff into prompt                           │            │
│  │  • Call Jules API                                    │            │
│  │  • Retry logic + error handling                      │            │
│  └────┬─────────────────────────────────────────────────┘            │
│       │                                                               │
│       ▼                                                               │
│  ┌─────────────────────────────────────────────────────┐            │
│  │  Comment Publisher                                   │            │
│  │  • Parse Jules findings                              │            │
│  │  • Map to file:line positions                        │            │
│  │  • Post inline PR comments via GitHub API           │            │
│  │  • Post check run summary                            │            │
│  └────┬─────────────────────────────────────────────────┘            │
│       │                                                               │
│       ▼                                                               │
│  ┌─────────────────────────────────────────────────────┐            │
│  │  Database (Optional)                                 │            │
│  │  • Store review history                              │            │
│  │  • Track processed commits                           │            │
│  └──────────────────────────────────────────────────────┘            │
│                                                                       │
└───────────────────────────┬───────────────────────────────────────────┘
                            │
                            │ POST /api/review
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      GOOGLE JULES API                                │
│  • Code analysis                                                     │
│  • Bug detection                                                     │
│  • Improvement suggestions                                           │
└─────────────────────────────────────────────────────────────────────┘
```

## Technical Flow

### 1. Installation & Setup
```
User installs GitHub App on repository
   │
   ├─ App requests permissions:
   │  • Read code (contents: read)
   │  • Write PR comments (pull_requests: write)
   │  • Create check runs (checks: write)
   │
   └─ GitHub generates installation_id & stores access token
```

### 2. Event Trigger
```
Developer pushes commit or opens PR
   │
   └─> GitHub sends webhook to your server
       POST https://your-server.com/webhook
       Headers:
         - X-GitHub-Event: push / pull_request
         - X-Hub-Signature-256: <signature>
       Body:
         {
           "action": "opened",
           "pull_request": {...},
           "repository": {...},
           "installation": {"id": 12345}
         }
```

### 3. Webhook Processing
```
Your Server receives webhook
   │
   ├─ Step 1: Verify GitHub signature (HMAC-SHA256)
   │   if invalid -> reject request
   │
   ├─ Step 2: Parse event type
   │   • pull_request.opened
   │   • pull_request.synchronize
   │   • push to main/master/develop
   │
   ├─ Step 3: Extract metadata
   │   • repo: owner/name
   │   • PR number or commit SHA
   │   • base_ref and head_ref
   │   • installation_id
   │
   └─ Step 4: Queue review job
       (async processing recommended)
```

### 4. Diff Extraction
```
GET https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}
Authorization: Bearer <installation_token>

Response:
{
  "diff_url": "https://github.com/owner/repo/pull/123.diff"
}
   │
   ├─ Fetch diff content
   │  GET {diff_url}
   │
   └─ Parse unified diff format
      • Extract changed files
      • Map line numbers
      • Filter large files (>50KB warning)
```

### 5. Jules API Review
```
Build prompt:
   template = load("prompt-template.md")
   prompt = template.replace("{DIFF_CONTENT}", diff)

POST https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent
Authorization: Bearer <JULES_API_KEY>
Content-Type: application/json
{
  "contents": [{
    "parts": [{"text": prompt}]
  }],
  "generationConfig": {
    "temperature": 0.3,
    "maxOutputTokens": 8192
  }
}

Response:
{
  "candidates": [{
    "content": {
      "parts": [{"text": "<findings in structured format>"}]
    }
  }]
}
   │
   └─ Parse findings:
      • severity: CRITICAL|HIGH|MEDIUM|LOW
      • file: path/to/file.py
      • line: 42
      • message: "Bug description"
      • suggestion: "Fix recommendation"
```

### 6. Publish Comments
```
For each finding:

POST https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/comments
Authorization: Bearer <installation_token>
{
  "body": "🔴 **CRITICAL**: Buffer overflow detected\n\n**Suggestion**: Use bounds checking",
  "commit_id": "<head_sha>",
  "path": "src/main.c",
  "line": 42,
  "side": "RIGHT"
}

Create check run summary:
POST https://api.github.com/repos/{owner}/{repo}/check-runs
{
  "name": "Jules Code Review",
  "head_sha": "<commit_sha>",
  "status": "completed",
  "conclusion": "neutral",
  "output": {
    "title": "Found 5 issues",
    "summary": "2 CRITICAL, 1 HIGH, 2 MEDIUM",
    "text": "<markdown table of findings>"
  }
}
```

## Implementation Stack

**Backend Server:**
- Python: Flask or FastAPI
- Node.js: Express

**Required Libraries:**
- `PyGithub` or `@octokit/rest` - GitHub API client
- `requests` - HTTP client for Jules API
- `cryptography` - Webhook signature verification
- `redis` or `celery` - Job queue (optional)

**Deployment:**
- Heroku / Railway / Render (free tier)
- AWS Lambda + API Gateway (serverless)
- DigitalOcean App Platform

**Environment Variables:**
```
GITHUB_APP_ID=123456
GITHUB_PRIVATE_KEY=<PEM key>
GITHUB_WEBHOOK_SECRET=<random_secret>
JULES_API_KEY=<your_key>
```

## API Endpoints

```
POST /webhook              - GitHub webhook receiver
GET  /health              - Health check
GET  /install             - GitHub App installation redirect
```

## Key GitHub App Permissions

- **Repository permissions:**
  - Contents: Read
  - Pull requests: Read & Write
  - Checks: Write
  
- **Subscribe to events:**
  - Pull request
  - Push

## Next Steps to Build

1. **Create GitHub App:**
   - Go to GitHub Settings → Developer settings → GitHub Apps
   - Set webhook URL: `https://your-server.com/webhook`
   - Generate webhook secret
   - Download private key

2. **Deploy server** with webhook handler

3. **Test on a repository** before public release
