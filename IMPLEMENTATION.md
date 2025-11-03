# Jules Code Review POC - Implementation Guide

## Overview

This document details the implementation of the Jules Code Review POC, a GitHub Actions-based automated code reviewer that analyzes commits and PRs using the Google Jules API.

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    GitHub Event                             │
│              (PR opened/updated or push)                    │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│         GitHub Actions Workflow (jules-review.yml)          │
└────────────────────────┬────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
   ┌─────────┐    ┌──────────────┐  ┌──────────────┐
   │Checkout │    │Compute Diff  │  │Install Deps  │
   │ Repo    │    │(compute_diff)│  │(requirements)│
   └─────────┘    └──────────────┘  └──────────────┘
        │                │                │
        └────────────────┼────────────────┘
                         │
                         ▼
            ┌────────────────────────┐
            │  Jules Review Step     │
            │  (jules_review.py)     │
            │                        │
            │ 1. Load prompt template│
            │ 2. Build prompt       │
            │ 3. Call Jules API     │
            │ 4. Parse findings     │
            └────────────────────────┘
                         │
                         ▼
            ┌────────────────────────┐
            │ Publish Comments Step  │
            │ (publish_comments.py)  │
            │                        │
            │ 1. Post PR comments    │
            │ 2. Post commit comments│
            │ 3. Generate summary    │
            └────────────────────────┘
                         │
                         ▼
            ┌────────────────────────┐
            │  GitHub Comments       │
            │  & Job Summary         │
            └────────────────────────┘
```

## Core Components

### 1. Workflow: `.github/workflows/jules-review.yml`

**Purpose**: Orchestrates the entire review process

**Key Features**:
- Triggers on PR events and pushes to main branches
- Sets up Python environment
- Runs each step sequentially
- Uploads findings as artifact for audit trail
- Handles failures gracefully

**Permissions Required**:
- `contents: read` - Read repository code
- `pull-requests: write` - Post PR comments
- `checks: write` - Create check runs

### 2. Script: `scripts/compute_diff.py`

**Purpose**: Extract git diff from the triggering event

**Flow**:
1. Load GitHub event from `GITHUB_EVENT_PATH`
2. Determine event type (PR or push)
3. Compute appropriate diff:
   - **PR**: `git diff origin/base...origin/head`
   - **Push**: `git diff before_sha...after_sha`
4. Handle edge cases (new branches, force pushes)
5. Save diff to file

**Key Functions**:
- `get_event_context()` - Extract event metadata
- `compute_diff()` - Generate diff based on event type
- `run_command()` - Execute git commands with error handling

**Output**: `diff.patch` (unified diff format)

### 3. Script: `scripts/jules_review.py`

**Purpose**: Call Jules API and parse findings

**Flow**:
1. Load diff from file
2. Load prompt template from `config/prompt-template.md`
3. Build prompt by inserting diff into template
4. Call Jules API with retry logic:
   - Max 3 attempts
   - Exponential backoff on rate limits (429)
   - Timeout: 60 seconds
5. Parse response into standardized findings
6. Save findings to JSON

**Key Classes**:
- `JulesReviewClient` - Handles API communication
  - `call_review_api()` - Makes API request with retries
  - `parse_findings()` - Converts API response to standard format

**Output**: `findings.json` with findings array

**Error Handling**:
- Missing API key → Raises ValueError
- API errors → Retries with backoff
- Large diffs → Truncates with notice
- Empty diff → Skips review

### 4. Script: `scripts/publish_comments.py`

**Purpose**: Post findings as GitHub comments

**Flow**:
1. Load findings from JSON
2. Determine event type (PR or push)
3. For each finding:
   - Format comment with severity and message
   - Post to appropriate GitHub endpoint
4. Generate job summary with severity breakdown
5. Write summary to `GITHUB_STEP_SUMMARY`

**Key Classes**:
- `GitHubCommentPublisher` - Handles GitHub API calls
  - `post_pr_review_comment()` - Inline PR comments
  - `post_commit_comment()` - Commit-level comments
  - `post_job_summary()` - Summary table

**Comment Format**:
```
**[SEVERITY]** Issue message

**Suggestion:** How to fix it
```

**Output**: Comments on GitHub + job summary

### 5. Script: `scripts/utils.py`

**Purpose**: Shared utilities for all scripts

**Key Functions**:
- `load_github_event()` - Load event JSON
- `get_event_context()` - Extract context metadata
- `parse_diff_file()` - Read diff file
- `save_json()` / `load_json()` - JSON I/O
- `log_info()` / `log_error()` / `log_debug()` - Logging

### 6. Config: `config/prompt-template.md`

**Purpose**: Jules prompt template with instructions

**Contents**:
- System instructions (expert reviewer, priorities)
- Severity level definitions
- Output format specification
- Placeholder for diff content: `{DIFF_CONTENT}`

**Customization**: Edit to adjust review behavior

## Data Flow

### Event → Diff

```
GitHub Event (GITHUB_EVENT_PATH)
    ↓
get_event_context() extracts:
  - event_name (pull_request, push)
  - base_ref, head_ref (for PR)
  - before, after (for push)
    ↓
compute_diff() runs:
  - git fetch origin base_ref
  - git diff origin/base...origin/head
    ↓
diff.patch (unified format)
```

### Diff → Findings

```
diff.patch
    ↓
load_prompt_template() reads config/prompt-template.md
    ↓
build_prompt() inserts diff into template
    ↓
JulesReviewClient.call_review_api() POSTs to Jules
    ↓
parse_findings() converts response to:
  [
    {
      "file": "path/to/file",
      "line": 42,
      "severity": "HIGH",
      "message": "Issue description",
      "suggestion": "How to fix"
    },
    ...
  ]
    ↓
findings.json
```

### Findings → Comments

```
findings.json
    ↓
GitHubCommentPublisher loads context:
  - is_pull_request
  - pull_number (if PR)
  - sha (if push)
    ↓
For each finding:
  - post_pr_review_comment() or post_commit_comment()
    ↓
GitHub API: POST /repos/{owner}/{repo}/pulls/{pr}/comments
GitHub API: POST /repos/{owner}/{repo}/commits/{sha}/comments
    ↓
Comments appear on GitHub
    ↓
post_job_summary() writes to GITHUB_STEP_SUMMARY
    ↓
Summary appears in workflow run
```

## Configuration

### Environment Variables

**Required**:
- `JULES_API_KEY` - Jules API authentication (secret)
- `GITHUB_TOKEN` - GitHub API authentication (default)
- `GITHUB_EVENT_PATH` - Path to event JSON (set by Actions)
- `GITHUB_REPOSITORY` - Repo in format owner/repo (set by Actions)
- `GITHUB_SHA` - Current commit SHA (set by Actions)

**Optional**:
- `DEBUG` - Enable debug logging (set to true)

### Secrets Setup

1. Go to repository Settings
2. Navigate to Secrets and variables → Actions
3. Create new repository secret:
   - Name: `JULES_API_KEY`
   - Value: Your Jules API key

### Workflow Customization

Edit `.github/workflows/jules-review.yml`:

```yaml
# Change trigger branches
on:
  push:
    branches: [main, develop, staging]

# Adjust Python version
python-version: '3.12'

# Add environment variables
env:
  LOG_LEVEL: DEBUG
```

## Testing

### Local Testing

```bash
# 1. Set up environment
export GITHUB_EVENT_PATH=examples/sample_event.json
export GITHUB_REPOSITORY=owner/repo
export GITHUB_SHA=xyz789uvw012
export GITHUB_TOKEN=your_token
export JULES_API_KEY=your_api_key

# 2. Test diff computation
python scripts/compute_diff.py --output test.patch

# 3. Test Jules review (mock)
# Edit scripts/jules_review.py to use mock response
python scripts/jules_review.py --diff test.patch --output findings.json

# 4. Test comment publishing
python scripts/publish_comments.py --findings findings.json
```

### Dry-Run on GitHub

1. Create test branch
2. Make small code change
3. Open PR
4. Monitor workflow run in Actions tab
5. Check PR comments

### Mock Testing

Use `examples/sample_findings.json` to test comment publishing without calling Jules API:

```bash
python scripts/publish_comments.py --findings examples/sample_findings.json
```

## Error Handling

### Scenario: Missing JULES_API_KEY

**Symptom**: "JULES_API_KEY environment variable not set"

**Cause**: Secret not configured in repository

**Fix**:
1. Go to Settings → Secrets and variables → Actions
2. Add `JULES_API_KEY` secret
3. Rerun workflow

### Scenario: API Rate Limit

**Symptom**: "API error: 429"

**Cause**: Too many requests to Jules API

**Handling**:
- Automatic retry with exponential backoff
- Max 3 attempts
- Waits 2s, 4s, 8s between attempts

### Scenario: Large Diff

**Symptom**: "Diff too large, truncating"

**Cause**: Diff exceeds 50KB

**Handling**:
- Truncates to 50KB
- Adds notice: "[... diff truncated due to size ...]"
- Continues with partial review

### Scenario: No Changes

**Symptom**: "No changes detected in diff"

**Cause**: Commit has no file changes

**Handling**:
- Skips review
- Saves empty findings
- No comments posted

## Limitations (v1)

1. **No Context Persistence**
   - Each review is independent
   - No learning from previous feedback
   - No team standards stored

2. **No Static Analysis**
   - Only Jules API analysis
   - No linter/security scanner integration
   - No dependency analysis

3. **Diff Size Limits**
   - Large diffs truncated at 50KB
   - May miss issues in large changes

4. **Comment Limitations**
   - Requires file path and line number
   - Can't comment on deleted lines
   - Deduplication is basic

5. **API Dependency**
   - Requires valid Jules API key
   - Workflow fails if API is down
   - No offline mode

## Future Enhancements

### Phase 2: Context Management
- Vector DB for storing past reviews
- Team coding standards
- Project-specific guidelines
- Learnings engine

### Phase 3: Advanced Analysis
- Static analyzer integration (linters, security scanners)
- Dependency graph analysis
- Performance regression detection
- Architecture drift detection

### Phase 4: Multi-Platform
- GitLab support
- Bitbucket support
- Self-hosted Git support

### Phase 5: IDE Integration
- VS Code extension
- JetBrains plugin
- CLI tool for local reviews

## Performance Considerations

### Latency
- Diff computation: ~1s
- Jules API call: ~10-30s (depends on diff size)
- Comment posting: ~2-5s per comment
- **Total**: ~15-40s per review

### Scalability
- Workflow runs in parallel for different PRs
- GitHub Actions has rate limits (depends on plan)
- Jules API has rate limits (check documentation)

### Cost
- GitHub Actions: Free tier includes 2000 minutes/month
- Jules API: Pricing depends on usage (check documentation)

## Security Considerations

1. **API Key Protection**
   - Stored as repository secret
   - Not logged or exposed
   - Rotated regularly

2. **GitHub Token**
   - Limited to workflow scope
   - Expires after workflow completes
   - Only has required permissions

3. **Comment Sanitization**
   - Comments are plain text
   - No code execution risk
   - GitHub escapes HTML

4. **Diff Handling**
   - Diff is processed locally
   - Not sent to external services except Jules
   - Truncated for size limits

## Troubleshooting

### Workflow Not Triggering

**Check**:
1. Event type matches trigger (PR or push to main)
2. Workflow file is in `.github/workflows/`
3. Workflow is enabled in Actions tab
4. Branch protection rules don't block

### Comments Not Posting

**Check**:
1. `GITHUB_TOKEN` has `pull-requests: write` permission
2. Repository is not a fork (forks can't post comments)
3. Findings have valid file paths and line numbers
4. Jules API returned valid findings

### API Errors

**Check**:
1. Jules API key is valid
2. API endpoint is correct
3. Network connectivity is working
4. API rate limits not exceeded

## Debugging

### Enable Debug Logging

Set `DEBUG: true` in workflow:

```yaml
- name: Run Jules review
  env:
    JULES_API_KEY: ${{ secrets.JULES_API_KEY }}
    DEBUG: true
  run: python scripts/jules_review.py ...
```

### Check Artifacts

1. Go to workflow run
2. Download "review-findings" artifact
3. Inspect `findings.json` for parsed results

### View Logs

1. Go to workflow run
2. Click on job step
3. View step logs for detailed output

## Maintenance

### Regular Tasks

- **Weekly**: Check workflow runs for errors
- **Monthly**: Review and update prompt template
- **Quarterly**: Update dependencies in requirements.txt
- **Annually**: Review and update documentation

### Updating Dependencies

```bash
# Update requirements.txt
pip install --upgrade requests PyGithub python-dotenv
pip freeze > scripts/requirements.txt

# Commit and push
git add scripts/requirements.txt
git commit -m "Update dependencies"
```

## Support & Contribution

For issues, questions, or contributions:
1. Open GitHub issue with details
2. Include workflow run logs
3. Provide minimal reproduction case
4. Submit PR with fixes/enhancements

---

**Last Updated**: 2024-01-01
**Version**: 1.0.0
**Status**: POC - Ready for Testing
