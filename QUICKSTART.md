# Jules Code Review POC - Quick Start Guide

Get up and running with Jules Code Review in 5 minutes.

## Prerequisites

- GitHub repository with Actions enabled
- Google Jules API key
- Basic git knowledge

## Setup (5 minutes)

### Step 1: Add Repository Secret (1 min)

1. Go to your repository on GitHub
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Name: `JULES_API_KEY`
5. Value: Your Jules API key
6. Click **Add secret**

### Step 2: Verify Workflow File (1 min)

The workflow file is already included at `.github/workflows/jules-review.yml`

To verify:
```bash
ls -la .github/workflows/jules-review.yml
```

### Step 3: Verify Permissions (1 min)

1. Go to **Settings** → **Actions** → **General**
2. Under "Workflow permissions", select **Read and write permissions**
3. Click **Save**

### Step 4: Test on a PR (2 min)

1. Create a test branch:
   ```bash
   git checkout -b test/review
   ```

2. Make a code change (e.g., add a file with intentional issues):
   ```bash
   cat > test.py << 'EOF'
   def buggy():
       x = None
       return x + 1
   EOF
   ```

3. Commit and push:
   ```bash
   git add test.py
   git commit -m "Add test code"
   git push origin test/review
   ```

4. Open a PR on GitHub and wait for the workflow to run

5. Check the PR for comments from Jules

## What Happens

When you open a PR or push to main:

1. **Checkout** - Repository is cloned
2. **Compute Diff** - Changes are extracted
3. **Jules Review** - AI analyzes the code
4. **Publish Comments** - Findings are posted as comments
5. **Summary** - Results appear in job summary

## Viewing Results

### PR Comments

Comments appear directly on your PR with:
- **Severity level** (CRITICAL, HIGH, MEDIUM, LOW)
- **Issue description**
- **Suggested fix**

### Job Summary

Click on the workflow run to see:
- Table of findings by severity
- Total issue count
- Detailed issue list

### Artifacts

Download the "review-findings" artifact to inspect:
- Raw findings JSON
- Full API response
- Timestamps and metadata

## Customization

### Change Trigger Branches

Edit `.github/workflows/jules-review.yml`:

```yaml
on:
  push:
    branches: [main, develop, staging]  # Add/remove branches
```

### Customize Review Instructions

Edit `config/prompt-template.md`:

```markdown
# Your custom instructions here
- Focus on security issues
- Check for performance problems
- Verify error handling
```

### Filter by Severity

Edit `scripts/publish_comments.py` to only post certain severities:

```python
SEVERITY_FILTER = ["CRITICAL", "HIGH"]  # Only post critical/high
```

## Common Issues

### "JULES_API_KEY not set"

**Fix**: Add the secret to repository settings (see Step 1)

### "No comments posted"

**Possible causes**:
- Diff is empty (no changes)
- API key is invalid
- GitHub token lacks permissions

**Fix**: Check workflow logs for details

### "Workflow doesn't run"

**Fix**: Verify:
1. Event type matches trigger (PR or push to main)
2. Workflow file exists at `.github/workflows/jules-review.yml`
3. Workflow is enabled in Actions tab

## Next Steps

1. **Review the README** for detailed documentation
2. **Check IMPLEMENTATION.md** for architecture details
3. **Read TESTING.md** for comprehensive testing guide
4. **Customize the prompt template** for your project
5. **Gather team feedback** on findings quality

## File Structure

```
.
├── .github/workflows/
│   └── jules-review.yml          # Main workflow
├── scripts/
│   ├── compute_diff.py           # Extract changes
│   ├── jules_review.py           # Call Jules API
│   ├── publish_comments.py       # Post findings
│   ├── utils.py                  # Shared utilities
│   └── requirements.txt          # Dependencies
├── config/
│   └── prompt-template.md        # Review instructions
├── examples/
│   ├── sample_event.json         # Example GitHub event
│   ├── sample_diff.patch         # Example diff
│   └── sample_findings.json      # Example findings
├── README.md                     # Full documentation
├── IMPLEMENTATION.md             # Architecture guide
├── TESTING.md                    # Testing procedures
└── QUICKSTART.md                 # This file
```

## Support

- **Issues?** Check the README troubleshooting section
- **Questions?** See IMPLEMENTATION.md for detailed explanations
- **Testing?** Follow TESTING.md procedures
- **Bugs?** Open a GitHub issue with logs

## Tips

✅ **Do**:
- Start with small PRs to test
- Review the comments carefully
- Customize the prompt for your project
- Monitor workflow runs regularly

❌ **Don't**:
- Commit API keys to the repository
- Disable workflow permissions
- Ignore security findings
- Use on untrusted code

## Performance

Typical workflow run times:
- Small PR (1-5 files): 30-50 seconds
- Medium PR (5-20 files): 40-70 seconds
- Large PR (20+ files): 60-90 seconds

## Limitations (v1)

- No persistent context per project
- No integration with static analyzers
- Large diffs (>50KB) are truncated
- Requires valid Jules API key
- Comments only on files with line numbers

## What's Next?

Future versions will add:
- Team coding standards storage
- Static analyzer integration
- Learnings engine
- Multi-platform support (GitLab, Bitbucket)
- IDE integration

---

**Ready to go!** 🚀

Open a PR and watch Jules review your code.
