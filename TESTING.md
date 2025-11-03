# Jules Code Review POC - Testing Guide

## Overview

This guide provides comprehensive testing procedures for the Jules Code Review POC before deploying to production.

## Test Levels

### 1. Unit Testing (Local)

Test individual scripts in isolation.

#### Test: `compute_diff.py`

```bash
# Setup
export GITHUB_EVENT_PATH=examples/sample_event.json
export GITHUB_REPOSITORY=owner/repo
export GITHUB_SHA=xyz789uvw012

# Run
python scripts/compute_diff.py --output test_diff.patch

# Verify
cat test_diff.patch
# Should show unified diff format
```

**Expected Output**:
- File created: `test_diff.patch`
- Contains unified diff with `---` and `+++` headers
- Shows file changes with `@@` line markers

**Failure Cases**:
- Missing event file → FileNotFoundError
- Invalid git repository → CalledProcessError
- No changes → Empty diff (valid)

#### Test: `utils.py`

```bash
# Test event loading
python -c "
from scripts.utils import load_github_event, get_event_context
event = load_github_event()
print(f'Event: {event.get(\"action\")}')
context = get_event_context()
print(f'Context: {context}')
"
```

**Expected Output**:
- Event loaded from JSON
- Context extracted with all required fields
- No errors

### 2. Integration Testing (Local)

Test scripts working together with mock data.

#### Test: Full Pipeline with Mock

```bash
#!/bin/bash
set -e

# Setup
export GITHUB_EVENT_PATH=examples/sample_event.json
export GITHUB_REPOSITORY=owner/repo
export GITHUB_SHA=xyz789uvw012
export GITHUB_TOKEN=test_token
export JULES_API_KEY=test_key

# Step 1: Compute diff
echo "=== Step 1: Compute Diff ==="
python scripts/compute_diff.py --output test_diff.patch
echo "✓ Diff computed"

# Step 2: Mock Jules review (use sample findings)
echo "=== Step 2: Mock Jules Review ==="
cp examples/sample_findings.json test_findings.json
echo "✓ Findings loaded"

# Step 3: Publish comments (dry-run)
echo "=== Step 3: Publish Comments (Dry-Run) ==="
# Edit script to add --dry-run flag for testing
python scripts/publish_comments.py --findings test_findings.json
echo "✓ Comments prepared"

echo "=== All tests passed ==="
```

**Expected Output**:
- All steps complete without errors
- Findings JSON is valid
- Comments are formatted correctly

### 3. Workflow Testing (GitHub)

Test the workflow on GitHub with real events.

#### Test: Manual Workflow Dispatch

1. Go to repository → Actions
2. Select "Jules Code Review" workflow
3. Click "Run workflow"
4. Select branch (e.g., `main`)
5. Click "Run workflow"

**Expected Output**:
- Workflow runs successfully
- All steps complete (green checkmarks)
- Job summary appears in workflow run

#### Test: Pull Request

1. Create test branch: `git checkout -b test/review`
2. Make code changes (intentional bugs for testing)
3. Commit: `git commit -am "Test changes"`
4. Push: `git push origin test/review`
5. Open PR on GitHub
6. Wait for workflow to run

**Expected Output**:
- Workflow triggers automatically
- Comments appear on PR
- Job summary shows findings

**Example Test Code** (`test_code.py`):
```python
def buggy_function():
    x = None
    return x + 1  # TypeError: unsupported operand type(s)

def divide_by_zero():
    return 10 / 0  # ZeroDivisionError

def sql_injection(user_id):
    query = f"SELECT * FROM users WHERE id = {user_id}"  # SQL injection
    return query
```

#### Test: Push to Main

1. Create test branch: `git checkout -b test/push`
2. Make code changes
3. Commit: `git commit -am "Test push"`
4. Push to main: `git push origin test/push:main`
5. Wait for workflow to run

**Expected Output**:
- Workflow triggers on push
- Comments appear on commit
- Job summary shows findings

### 4. Error Scenario Testing

Test error handling and recovery.

#### Scenario: Missing API Key

**Setup**:
1. Remove `JULES_API_KEY` secret from repository
2. Open PR or push to main

**Expected**:
- Workflow runs
- Jules review step fails with clear error message
- Comment publishing step is skipped
- Job summary shows error

**Recovery**:
1. Add `JULES_API_KEY` secret
2. Rerun workflow

#### Scenario: Invalid API Key

**Setup**:
1. Set `JULES_API_KEY` to invalid value
2. Open PR

**Expected**:
- Workflow runs
- Jules API call fails with 401 Unauthorized
- Retry logic attempts 3 times
- Graceful failure with error message

#### Scenario: Large Diff

**Setup**:
1. Create large file (>50KB)
2. Make changes
3. Open PR

**Expected**:
- Diff is truncated at 50KB
- Review continues with truncated diff
- Warning message in findings
- Comments posted for available content

#### Scenario: No Changes

**Setup**:
1. Create empty commit: `git commit --allow-empty -m "Empty commit"`
2. Push to main

**Expected**:
- Workflow runs
- Diff is empty
- Review is skipped
- Job summary shows "No changes"

#### Scenario: Fork PR

**Setup**:
1. Fork repository
2. Make changes in fork
3. Open PR to original repo

**Expected**:
- Workflow runs
- Comment posting fails (forks can't post comments)
- Graceful fallback to summary only
- No errors in workflow

### 5. Performance Testing

Test workflow performance and timing.

#### Test: Review Latency

**Procedure**:
1. Open PR with small change (1-5 files)
2. Monitor workflow run time
3. Record each step duration

**Expected**:
- Checkout: ~2-5s
- Setup Python: ~5-10s
- Install deps: ~10-15s
- Compute diff: ~1-2s
- Jules review: ~15-30s (depends on API)
- Publish comments: ~3-5s
- **Total**: ~40-70s

#### Test: Concurrent Reviews

**Procedure**:
1. Open 5 PRs simultaneously
2. Monitor workflow queue
3. Check if all complete successfully

**Expected**:
- All workflows run in parallel
- No conflicts or failures
- All comments posted correctly

### 6. Data Validation Testing

Test data parsing and validation.

#### Test: Diff Parsing

```bash
python -c "
from scripts.utils import parse_diff_file

diff = parse_diff_file('examples/sample_diff.patch')
print(f'Diff length: {len(diff)}')
print(f'Lines: {len(diff.splitlines())}')
print('First 5 lines:')
for line in diff.splitlines()[:5]:
    print(f'  {line}')
"
```

**Expected**:
- Diff parsed successfully
- Contains valid unified diff format
- Line counts are reasonable

#### Test: Findings JSON

```bash
python -c "
import json
from scripts.utils import load_json

findings = load_json('examples/sample_findings.json')
print(f'Findings: {len(findings[\"findings\"])}')
for f in findings['findings']:
    print(f'  {f[\"file\"]}:{f[\"line\"]} [{f[\"severity\"]}]')
"
```

**Expected**:
- JSON parsed successfully
- All required fields present
- Severity values are valid (CRITICAL, HIGH, MEDIUM, LOW)

### 7. Security Testing

Test security aspects.

#### Test: API Key Not Exposed

```bash
# Run workflow with DEBUG=true
# Check logs for API key exposure
grep -r "JULES_API_KEY" .github/workflows/
# Should find no hardcoded keys
```

**Expected**:
- No API keys in logs
- No API keys in comments
- Secrets properly masked in output

#### Test: GitHub Token Scope

**Procedure**:
1. Check workflow permissions
2. Verify only required permissions granted

**Expected**:
- `contents: read` only
- `pull-requests: write` for comments
- No unnecessary permissions

### 8. Regression Testing

Test that changes don't break existing functionality.

#### Checklist

- [ ] Diff computation works for PRs
- [ ] Diff computation works for pushes
- [ ] Jules API integration works
- [ ] Comment posting works on PRs
- [ ] Comment posting works on commits
- [ ] Job summary is generated
- [ ] Error handling works
- [ ] Retry logic works
- [ ] Large diffs are handled
- [ ] Empty diffs are handled

### 9. User Acceptance Testing (UAT)

Test with real developers.

#### Test: Developer Workflow

1. Developer opens PR with code changes
2. Workflow runs automatically
3. Developer reviews comments
4. Developer makes changes based on feedback
5. Workflow runs again
6. Verify updated comments

**Expected**:
- Comments are helpful and accurate
- No false positives
- Suggestions are actionable
- Workflow doesn't block merges

#### Test: Team Feedback

1. Share workflow with team
2. Collect feedback on:
   - Comment quality
   - False positive rate
   - Usefulness of suggestions
   - Performance impact
3. Iterate based on feedback

## Test Checklist

### Pre-Deployment

- [ ] All unit tests pass
- [ ] Integration tests pass
- [ ] Workflow runs successfully on test PR
- [ ] Comments are posted correctly
- [ ] Job summary is generated
- [ ] Error scenarios handled gracefully
- [ ] Performance is acceptable
- [ ] Security review passed
- [ ] Documentation is complete
- [ ] Team has reviewed and approved

### Deployment

- [ ] Secrets configured in repository
- [ ] Workflow file is in `.github/workflows/`
- [ ] README updated with setup instructions
- [ ] Team notified of new workflow
- [ ] Monitoring set up for workflow failures

### Post-Deployment

- [ ] Monitor first 10 workflow runs
- [ ] Collect team feedback
- [ ] Fix any issues found
- [ ] Document lessons learned
- [ ] Plan next phase enhancements

## Continuous Testing

### Automated Tests

Create `.github/workflows/test.yml` for automated testing:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r scripts/requirements.txt
      - run: python -m pytest tests/
```

### Manual Testing Schedule

- **Weekly**: Run full test suite
- **Before deployment**: Complete UAT
- **After changes**: Regression testing
- **Quarterly**: Performance review

## Troubleshooting Test Failures

### Workflow Doesn't Trigger

**Check**:
1. Event type matches trigger
2. Branch matches filter
3. Workflow file syntax is valid
4. Workflow is enabled

### Comments Not Posted

**Check**:
1. Findings JSON is valid
2. File paths are correct
3. Line numbers are valid
4. GitHub token has permissions

### Jules API Fails

**Check**:
1. API key is valid
2. API endpoint is correct
3. Network connectivity
4. API rate limits

### Performance Issues

**Check**:
1. Diff size (truncate if needed)
2. API response time
3. GitHub API rate limits
4. Workflow runner performance

## Test Results Template

```markdown
# Test Results - [Date]

## Test Environment
- Repository: [repo]
- Branch: [branch]
- Workflow: [version]

## Test Summary
- Total Tests: [n]
- Passed: [n]
- Failed: [n]
- Skipped: [n]

## Detailed Results

### Unit Tests
- [ ] compute_diff.py
- [ ] jules_review.py
- [ ] publish_comments.py
- [ ] utils.py

### Integration Tests
- [ ] Full pipeline
- [ ] Error handling
- [ ] Performance

### Workflow Tests
- [ ] PR trigger
- [ ] Push trigger
- [ ] Manual dispatch

### Error Scenarios
- [ ] Missing API key
- [ ] Invalid API key
- [ ] Large diff
- [ ] No changes
- [ ] Fork PR

## Issues Found
1. [Issue description]
2. [Issue description]

## Recommendations
1. [Recommendation]
2. [Recommendation]

## Sign-Off
- Tested by: [name]
- Date: [date]
- Status: [PASS/FAIL]
```

---

**Last Updated**: 2024-01-01
**Version**: 1.0.0
