# Jules Code Review POC — Project Plan (v1)

## 1. Summary
- **Objective:** Build a proof-of-concept automated code reviewer that runs on every commit/PR using **GitHub Actions** and the **Google Jules API**.
- **Scope:** No persistent context per project. Each run analyzes the diff of the triggering commit and posts review comments back to GitHub.
- **Deliverables:**
  1. GitHub Actions workflow that orchestrates checkout, diff extraction, and Jules review call.
  2. Minimal client script to format prompts, call Jules, and emit review findings.
  3. Comment publishing step that maps findings to GitHub review comments.

## 2. Architecture Overview
```
GitHub Event (push / pull_request)
        │
        ▼
 GitHub Action Workflow
        │
        ├── Step 1: Checkout repo (full history for diff base)
        ├── Step 2: Compute diff for event (commit or PR range)
        ├── Step 3: Jules Review step
        │       ├─ Package diff + metadata into prompt
        │       ├─ Call Jules Review API (HTTPS, API key secret)
        │       └─ Parse findings (severity, path, line, message)
        └── Step 4: Post comments back to GitHub
                ├─ Inline comments (if PR)
                ├─ Commit comments (if push on default branch)
                └─ Job summary (table of findings)
```

### Key Components
- **`.github/workflows/jules-review.yml`:** Entry workflow.
- **`scripts/jules_review.py` (or Node equivalent):** Handles API call and response parsing.
- **`scripts/post_comments.py`:** Posts review results using GitHub REST API (or reuse `gh api`).
- **Secrets:**
  - `JULES_API_KEY`: stored in repo/org secrets.
  - `GITHUB_TOKEN`: default Actions token (requires `pull-requests: write`).

## 3. Repository Structure (v1)
```
root/
├── .github/
│   └── workflows/
│       └── jules-review.yml     # GitHub Actions workflow definition
├── scripts/
│   ├── jules_review.py          # Calls Jules API with diff payload
│   ├── github_comments.py       # Helper to post review comments (optional)
│   └── utils.py                 # Shared utilities (parse diff, load env)
├── config/
│   └── prompt-template.md       # Base prompt string with placeholders
└── docs/
    └── project-plan.md          # This document
```
*Note:* combine helper scripts if keeping footprint minimal.

## 4. Workflow Mechanics

### 4.1 Trigger Strategy
- **Pull Requests:** Analyze `merge-base(pr.base, pr.head)` diff; post inline review comments.
- **Push to default branch:** Analyze `before` → `after` commit diff; post commit-level comments.

### 4.2 Workflow Draft
```yaml
name: jules-review

on:
  pull_request:
    types: [opened, synchronize, reopened]
  push:
    branches: [main]

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r scripts/requirements.txt

      - name: Compute diff
        id: diff
        run: |
          python scripts/compute_diff.py \
            --event-path "$GITHUB_EVENT_PATH" \
            --output diff.patch

      - name: Run Jules review
        id: review
        env:
          JULES_API_KEY: ${{ secrets.JULES_API_KEY }}
        run: |
          python scripts/jules_review.py \
            --diff diff.patch \
            --event-path "$GITHUB_EVENT_PATH" \
            --output findings.json

      - name: Publish comments
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          python scripts/publish_comments.py \
            --findings findings.json \
            --event-path "$GITHUB_EVENT_PATH"
```

### 4.3 Diff Handling
- `compute_diff.py` determines base/head:
  - PRs: `git diff origin/${{ github.base_ref }}...${{ github.head_ref }}`.
  - Push: `git diff ${{ github.event.before }} ${{ github.event.after }}`.
- Store diff in unified format; optionally chunk per file if size > Jules limit.

### 4.4 Jules Prompt Template
- Base template in `config/prompt-template.md` includes:
  - System instructions (e.g., “expert reviewer, prioritize correctness & security”).
  - Repo metadata (language hints, style notes if any).
  - Diff payload inserted per file.
- `jules_review.py` populates template, performs POST request, handles retries (429/5xx with exponential backoff), and emits normalized findings.

### 4.5 Posting Comments
- `publish_comments.py` maps findings to GitHub API endpoints:
  - PR inline: `POST /repos/{owner}/{repo}/pulls/{pull_number}/comments` with `path`, `line`, `side`.
  - Commit comments: `POST /repos/{owner}/{repo}/commits/{sha}/comments`.
- Deduplicate comments using `hash(file + line + message)` to avoid duplicates on reruns.
- Job summary: Markdown table with severity counts and links.

## 5. Setup Checklist
1. **Repository configuration**
   - Add workflow + scripts + config.
   - Ensure `requirements.txt` lists dependencies (e.g., `requests`, `pygithub`).
2. **Secrets**
   - Add `JULES_API_KEY` at repo/org level.
3. **Permissions**
   - Confirm Actions has `pull-requests: write` to post comments.
4. **Testing**
   - Dry-run workflow using `workflow_dispatch` on sample branch.
   - Mock Jules response (local run) to validate comment posting before using real API.
5. **Roll-out**
   - Enable branch protection requiring workflow success (optional).

## 6. Implementation Tasks & Milestones
| Milestone | Tasks | Owner | Target |
|-----------|-------|-------|--------|
| **M1 – Skeleton (Day 1)** | Create repo structure; add placeholder workflow and scripts; configure secrets. | DEV | Day 1 |
| **M2 – Jules Integration (Day 2)** | Implement diff script, prompt templating, Jules API client with retries; parse response into findings. | DEV | Day 2 |
| **M3 – GitHub Commenting (Day 3)** | Build comment publisher; support PR & commit modes; add dedupe logic. | DEV | Day 3 |
| **M4 – QA & Validation (Day 4)** | Run on sample PRs; adjust prompt; add logging & failure handling; document known limitations. | DEV | Day 4 |
| **M5 – Documentation (Day 5)** | Finalize README, usage guide, troubleshooting tips. | DEV | Day 5 |

## 7. Risks & Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| Jules rate limits or downtime | Review step fails | Implement retry + graceful failure; mark job warning without blocking merges initially |
| Large diffs exceed prompt limits | Missing coverage | Chunk per file; truncate with notice; encourage PR size limits |
| Posting comments on forks (no secrets) | Review skipped | Detect forked PRs; fallback to summary only |
| False positives | Developer trust erosion | Allow severity filtering; surface as suggestions initially |

## 8. Future Enhancements (Beyond v1)
1. Persist per-project context (vector DB, style guides).
2. Integrate static analyzer outputs into prompt.
3. Implement learnings engine to remember decisions.
4. Support additional hosting providers (GitLab, Bitbucket).
5. Add CLI/IDE integration similar to CodeRabbit.

---
**Status:** v1 POC plan ready for execution.
