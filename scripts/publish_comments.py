#!/usr/bin/env python3
"""Publish code review findings as GitHub comments."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from utils import get_event_context, load_json, log_error, log_info


class GitHubCommentPublisher:
    """Publish review findings as GitHub comments."""
    
    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        })
    
    def post_pr_review_comment(
        self,
        pull_number: int,
        path: str,
        line: int,
        message: str,
    ) -> bool:
        """Post inline comment on PR."""
        url = f"https://api.github.com/repos/{self.repo}/pulls/{pull_number}/comments"
        
        payload = {
            "body": message,
            "commit_id": os.getenv("GITHUB_SHA"),
            "path": path,
            "line": line,
        }
        
        try:
            response = self.session.post(url, json=payload)
            if response.status_code == 201:
                log_info(f"Posted comment on {path}:{line}")
                return True
            else:
                log_error(f"Failed to post comment: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            log_error(f"Error posting comment: {e}")
            return False
    
    def post_commit_comment(
        self,
        sha: str,
        path: str,
        line: int,
        message: str,
    ) -> bool:
        """Post comment on commit."""
        url = f"https://api.github.com/repos/{self.repo}/commits/{sha}/comments"
        
        payload = {
            "body": message,
            "path": path,
            "line": line,
        }
        
        try:
            response = self.session.post(url, json=payload)
            if response.status_code == 201:
                log_info(f"Posted commit comment on {path}:{line}")
                return True
            else:
                log_error(f"Failed to post commit comment: {response.status_code}")
                return False
        except Exception as e:
            log_error(f"Error posting commit comment: {e}")
            return False
    
    def post_job_summary(self, findings: List[Dict[str, Any]]) -> None:
        """Post job summary with findings overview."""
        summary_path = os.getenv("GITHUB_STEP_SUMMARY")
        if not summary_path:
            log_info("GITHUB_STEP_SUMMARY not set, skipping summary")
            return
        
        # Group findings by severity
        by_severity = {}
        for finding in findings:
            severity = finding.get("severity", "UNKNOWN")
            by_severity.setdefault(severity, []).append(finding)
        
        # Build markdown table
        summary = "# Code Review Results\n\n"
        summary += "| Severity | Count |\n"
        summary += "|----------|-------|\n"
        
        for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            count = len(by_severity.get(severity, []))
            summary += f"| {severity} | {count} |\n"
        
        summary += f"\n**Total Issues:** {len(findings)}\n\n"
        
        if findings:
            summary += "## Issues\n\n"
            for finding in findings[:20]:  # Limit to first 20 in summary
                file = finding.get("file", "unknown")
                line = finding.get("line", 0)
                severity = finding.get("severity", "UNKNOWN")
                message = finding.get("message", "")
                summary += f"- **{severity}** `{file}:{line}` - {message}\n"
            
            if len(findings) > 20:
                summary += f"\n... and {len(findings) - 20} more issues\n"
        else:
            summary += "✅ No issues found!\n"
        
        # Write summary
        Path(summary_path).parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, "a") as f:
            f.write(summary)
        
        log_info("Job summary posted")


def get_comment_hash(file: str, line: int, message: str) -> str:
    """Generate hash for deduplication."""
    content = f"{file}:{line}:{message}"
    return hashlib.md5(content.encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Publish review comments to GitHub")
    parser.add_argument("--findings", required=True, help="Path to findings JSON file")
    parser.add_argument("--event-path", default=None, help="Path to GitHub event JSON")
    
    args = parser.parse_args()
    
    try:
        # Get GitHub token
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            raise ValueError("GITHUB_TOKEN environment variable not set")
        
        # Load findings and context
        findings_data = load_json(args.findings)
        findings = findings_data.get("findings", [])
        context = findings_data.get("context", {})
        
        if "error" in findings_data:
            log_error(f"Review had error: {findings_data['error']}")
            # Still post summary
        
        repo = os.getenv("GITHUB_REPOSITORY", "")
        if not repo:
            raise ValueError("GITHUB_REPOSITORY environment variable not set")
        
        publisher = GitHubCommentPublisher(token, repo)
        
        # Post comments based on event type
        if context.get("is_pull_request"):
            pull_number = context.get("pull_number")
            log_info(f"Publishing {len(findings)} comments to PR #{pull_number}")
            
            posted = 0
            for finding in findings:
                file = finding.get("file", "")
                line = finding.get("line", 0)
                message = finding.get("message", "")
                suggestion = finding.get("suggestion", "")
                severity = finding.get("severity", "MEDIUM")
                
                if not file or line <= 0:
                    log_info(f"Skipping finding without file/line: {message}")
                    continue
                
                # Format comment
                comment = f"**[{severity}]** {message}"
                if suggestion:
                    comment += f"\n\n**Suggestion:** {suggestion}"
                
                if publisher.post_pr_review_comment(pull_number, file, line, comment):
                    posted += 1
            
            log_info(f"Posted {posted}/{len(findings)} comments")
        else:
            # Push event: post commit comments
            sha = context.get("after", os.getenv("GITHUB_SHA", ""))
            log_info(f"Publishing {len(findings)} comments to commit {sha[:7]}")
            
            posted = 0
            for finding in findings:
                file = finding.get("file", "")
                line = finding.get("line", 0)
                message = finding.get("message", "")
                suggestion = finding.get("suggestion", "")
                severity = finding.get("severity", "MEDIUM")
                
                if not file or line <= 0:
                    continue
                
                comment = f"**[{severity}]** {message}"
                if suggestion:
                    comment += f"\n\n**Suggestion:** {suggestion}"
                
                if publisher.post_commit_comment(sha, file, line, comment):
                    posted += 1
            
            log_info(f"Posted {posted}/{len(findings)} comments")
        
        # Post job summary
        publisher.post_job_summary(findings)
        
        log_info("Comment publishing complete")
        
    except Exception as e:
        log_error(f"Failed to publish comments: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
