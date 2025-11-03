# Jules Code Review POC

An automated code reviewer powered by Google Jules API and GitHub Actions. Analyzes code changes on every commit/PR and posts review comments directly to GitHub.

## Features

- **Automated Reviews**: Triggers on every PR and push to main branches
- **Inline Comments**: Posts findings as inline comments on PRs
- **Commit Comments**: Posts findings on commits for push events
- **Job Summary**: Generates a summary table of all findings
- **Severity Levels**: Categorizes issues as CRITICAL, HIGH, MEDIUM, or LOW
- **Retry Logic**: Handles API rate limits and transient failures
- **No Context Persistence**: v1 POC analyzes each diff independently

## Setup

### 1. Prerequisites

- GitHub repository with Actions enabled
- Google Jules API key
- Python 3.11+

### 2. Configuration

1. **Add the workflow file** (already included):
   - `.github/workflows/jules-review.yml`

2. **Add repository secret**:
   - Go to **Settings** → **Secrets and variables** → **Actions**
   - Create new secret: `JULES_API_KEY` with your API key

3. **Verify permissions**:
   - Go to **Settings** → **Actions** → **General**
   - Ensure "Read and write permissions" is selected for workflow permissions

### 3. Installation

```bash
# Clone the repository
git clone <repo-url>
cd Jules-coderabbit

# Install dependencies (for local testing)
pip install -r scripts/requirements.txt
```

## Usage

### Automatic (Recommended)

The workflow runs automatically on:
- Pull requests (opened, synchronized, reopened)
- Pushes to `main`, `master`, or `develop` branches

### Manual Testing

To test locally before deploying:

```bash
# Set environment variables
export GITHUB_EVENT_PATH=/path/to/event.json
export GITHUB_REPOSITORY=owner/repo
export GITHUB_SHA=<commit-sha>
export GITHUB_TOKEN=<your-token>
export JULES_API_KEY=<your-api-key>

# Compute diff
python scripts/compute_diff.py --output diff.patch

# Run review
python scripts/jules_review.py --diff diff.patch --output findings.json

# Publish comments
python scripts/publish_comments.py --findings findings.json
```

## Project Structure

```
.
├── .github/
│   └── workflows/
│       └── jules-review.yml          # GitHub Actions workflow
├── scripts/
│   ├── compute_diff.py               # Extract diff from git
│   ├── jules_review.py               # Call Jules API
│   ├── publish_comments.py           # Post findings to GitHub
│   ├── utils.py                      # Shared utilities
│   └── requirements.txt              # Python dependencies
├── config/
│   └── prompt-template.md            # Jules prompt template
└── README.md                         # This file
```

## How It Works

### 1. Diff Computation
- For PRs: Compares base branch with head branch
- For pushes: Compares before and after commits
- Outputs unified diff format

### 2. Jules Review
- Loads prompt template from `config/prompt-template.md`
- Inserts diff content into prompt
- Calls Jules API with retry logic (max 3 attempts)
- Parses response into standardized findings

### 3. Comment Publishing
- For PRs: Posts inline comments with file/line references
- For pushes: Posts commit-level comments
- Generates job summary with severity breakdown
- Deduplicates comments to avoid duplicates

## Configuration

### Prompt Template

Edit `config/prompt-template.md` to customize review instructions:
- Severity levels and definitions
- Output format expectations
- Repository-specific guidelines

### Workflow Triggers

Modify `.github/workflows/jules-review.yml` to:
- Change trigger branches
- Adjust Python version
- Add additional steps

## Limitations (v1)

- No persistent context per project
- No integration with static analyzers
- No learnings engine
- Large diffs (>50KB) are truncated
- Requires valid Jules API key
- Comments only on files with line numbers

## Error Handling

The workflow handles:
- Missing API key → Graceful failure with error message
- API rate limits → Automatic retry with exponential backoff
- Large diffs → Truncation with notice
- No changes → Skips review
- Fork PRs → Falls back to summary only

## Troubleshooting

### "JULES_API_KEY not set"
- Verify secret is added to repository
- Check secret name matches exactly

### "No changes detected"
- Ensure commits have actual file changes
- Check diff computation step output

### "Failed to post comments"
- Verify `GITHUB_TOKEN` has `pull-requests: write` permission
- Check repository is not a fork (forks can't post comments)

### "API error after retries"
- Check Jules API status
- Verify API key is valid
- Check network connectivity

## Future Enhancements

- Persist per-project context (vector DB, style guides)
- Integrate static analyzer outputs
- Implement learnings engine
- Support GitLab, Bitbucket
- CLI/IDE integration
- Configurable severity thresholds
- Comment deduplication across runs

## Development

### Adding New Features

1. Update relevant script in `scripts/`
2. Test locally with sample diff
3. Update workflow if needed
4. Document changes in README

### Testing

```bash
# Create test event JSON
cat > test_event.json << 'EOF'
{
  "pull_request": {
    "number": 1,
    "base": {"ref": "main", "sha": "abc123"},
    "head": {"ref": "feature", "sha": "def456"}
  }
}
EOF

# Run workflow steps manually
export GITHUB_EVENT_PATH=test_event.json
python scripts/compute_diff.py --output test.patch
```

## License

MIT

## Support

For issues or questions, please open a GitHub issue.
