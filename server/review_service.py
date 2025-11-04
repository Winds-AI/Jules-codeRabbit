"""Review orchestration service."""

import os
from typing import Dict, Any

from github_client import GitHubClient
from jules_client import JulesReviewClient, build_prompt
from utils import log_info, log_error


def process_review(payload: Dict[str, Any]) -> None:
    """Main review processing function."""
    try:
        # Extract context from webhook payload
        context = extract_context(payload)
        log_info(f"Processing review for {context['repo']} - {context['event_type']}")
        
        # Initialize GitHub client
        github = create_github_client(context["installation_id"])
        
        # Fetch diff
        diff = fetch_diff(github, context)
        if not diff.strip():
            log_info("No changes in diff, skipping review")
            return
        
        # Call Jules API
        findings = call_jules(diff, context)
        log_info(f"Found {len(findings)} issues")
        
        # Post comments
        post_comments(github, context, findings)
        
        # Create check run summary
        create_summary(github, context, findings)
        
        log_info("Review processing complete")
        
    except Exception as e:
        log_error(f"Review processing failed: {e}")
        # Optionally post error comment to PR/commit


def extract_context(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract relevant context from webhook payload."""
    context = {
        "installation_id": payload["installation"]["id"],
        "repo_full": payload["repository"]["full_name"],
        "repo": payload["repository"]["name"],
        "owner": payload["repository"]["owner"]["login"]
    }
    
    # Pull request event
    if "pull_request" in payload:
        pr = payload["pull_request"]
        context.update({
            "event_type": "pull_request",
            "pr_number": pr["number"],
            "head_sha": pr["head"]["sha"],
            "base_ref": pr["base"]["ref"],
            "head_ref": pr["head"]["ref"]
        })
    # Push event
    elif "commits" in payload:
        context.update({
            "event_type": "push",
            "sha": payload["after"],
            "ref": payload["ref"],
            "before": payload["before"]
        })
    
    return context


def create_github_client(installation_id: int) -> GitHubClient:
    """Create authenticated GitHub client."""
    app_id = os.getenv("GITHUB_APP_ID")
    private_key = os.getenv("GITHUB_PRIVATE_KEY")
    
    if not app_id or not private_key:
        raise ValueError("GITHUB_APP_ID and GITHUB_PRIVATE_KEY must be set")
    
    return GitHubClient(app_id, private_key, installation_id)


def fetch_diff(github: GitHubClient, context: Dict[str, Any]) -> str:
    """Fetch diff based on event type."""
    if context["event_type"] == "pull_request":
        return github.fetch_pr_diff(
            context["owner"],
            context["repo"],
            context["pr_number"]
        )
    else:
        return github.fetch_commit_diff(
            context["owner"],
            context["repo"],
            context["sha"]
        )


def call_jules(diff: str, context: Dict[str, Any]) -> list:
    """Call Jules API to review code."""
    api_key = os.getenv("JULES_API_KEY")
    if not api_key:
        raise ValueError("JULES_API_KEY must be set")
    
    client = JulesReviewClient(api_key)
    
    # Build prompt with diff
    prompt = build_prompt(diff, context)
    
    # Call API
    response = client.call_review_api(prompt)
    
    # Parse findings
    findings = client.parse_findings(response)
    
    return findings


def post_comments(github: GitHubClient, context: Dict[str, Any], findings: list) -> None:
    """Post review comments to GitHub."""
    posted = 0
    
    for finding in findings:
        file = finding.get("file", "")
        line = finding.get("line", 0)
        message = finding.get("message", "")
        suggestion = finding.get("suggestion", "")
        severity = finding.get("severity", "MEDIUM")
        
        # Skip invalid findings
        if not file or line <= 0 or not message:
            continue
        
        # Format comment with emoji
        severity_emoji = {
            "CRITICAL": "🔴",
            "HIGH": "🟠",
            "MEDIUM": "🟡",
            "LOW": "🟢"
        }
        emoji = severity_emoji.get(severity, "ℹ️")
        
        comment = f"{emoji} **[{severity}]** {message}"
        if suggestion:
            comment += f"\n\n**Suggestion:** {suggestion}"
        
        # Post comment
        if context["event_type"] == "pull_request":
            success = github.post_pr_comment(
                context["owner"],
                context["repo"],
                context["pr_number"],
                context["head_sha"],
                file,
                line,
                comment
            )
        else:
            success = github.post_commit_comment(
                context["owner"],
                context["repo"],
                context["sha"],
                file,
                line,
                comment
            )
        
        if success:
            posted += 1
    
    log_info(f"Posted {posted}/{len(findings)} comments")


def create_summary(github: GitHubClient, context: Dict[str, Any], findings: list) -> None:
    """Create check run summary."""
    # Count by severity
    severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for finding in findings:
        severity = finding.get("severity", "MEDIUM")
        if severity in severity_counts:
            severity_counts[severity] += 1
    
    # Determine conclusion
    if severity_counts["CRITICAL"] > 0:
        conclusion = "failure"
    elif severity_counts["HIGH"] > 0:
        conclusion = "neutral"
    else:
        conclusion = "success"
    
    # Build summary
    title = f"Found {len(findings)} issues"
    summary = "## Code Review Results\n\n"
    summary += "| Severity | Count |\n"
    summary += "|----------|-------|\n"
    
    for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        count = severity_counts[severity]
        summary += f"| {severity} | {count} |\n"
    
    if findings:
        summary += "\n### Top Issues\n\n"
        for finding in findings[:10]:
            file = finding.get("file", "unknown")
            line = finding.get("line", 0)
            severity = finding.get("severity", "MEDIUM")
            message = finding.get("message", "")
            summary += f"- **{severity}** `{file}:{line}` - {message}\n"
        
        if len(findings) > 10:
            summary += f"\n... and {len(findings) - 10} more issues\n"
    else:
        summary += "\n✅ No issues found!\n"
    
    # Get SHA for check run
    sha = context.get("head_sha") or context.get("sha")
    
    # Create check run
    github.create_check_run(
        context["owner"],
        context["repo"],
        sha,
        "Jules Code Review",
        conclusion,
        title,
        summary
    )
