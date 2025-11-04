"""GitHub API client for fetching diffs and posting comments."""

import time
import jwt
import requests
from typing import Dict, Any, Optional

from utils import log_info, log_error


class GitHubClient:
    """Client for GitHub API operations."""
    
    def __init__(self, app_id: str, private_key: str, installation_id: int):
        self.app_id = app_id
        self.private_key = private_key
        self.installation_id = installation_id
        self.token = None
        self.token_expires = 0
    
    def _get_jwt(self) -> str:
        """Generate JWT for GitHub App authentication."""
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 600,  # 10 minutes
            "iss": self.app_id
        }
        return jwt.encode(payload, self.private_key, algorithm="RS256")
    
    def _get_installation_token(self) -> str:
        """Get installation access token (valid 1 hour)."""
        # Return cached token if still valid
        if self.token and time.time() < self.token_expires - 60:
            return self.token
        
        # Get new token
        jwt_token = self._get_jwt()
        url = f"https://api.github.com/app/installations/{self.installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        response = requests.post(url, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        self.token = data["token"]
        self.token_expires = time.time() + 3600  # 1 hour
        
        log_info("Got installation token")
        return self.token
    
    def _make_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make authenticated GitHub API request."""
        token = self._get_installation_token()
        headers = kwargs.pop("headers", {})
        headers.update({
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        })
        
        response = requests.request(method, url, headers=headers, **kwargs)
        return response
    
    def fetch_pr_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """Fetch PR diff in unified format."""
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        
        # Get PR details
        response = self._make_request("GET", url)
        response.raise_for_status()
        pr_data = response.json()
        
        # Fetch diff
        diff_url = pr_data["diff_url"]
        token = self._get_installation_token()
        headers = {"Authorization": f"token {token}"}
        
        diff_response = requests.get(diff_url, headers=headers)
        diff_response.raise_for_status()
        
        log_info(f"Fetched PR #{pr_number} diff: {len(diff_response.text)} bytes")
        return diff_response.text
    
    def fetch_commit_diff(self, owner: str, repo: str, sha: str) -> str:
        """Fetch commit diff in unified format."""
        url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}"
        
        token = self._get_installation_token()
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3.diff"
        }
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        log_info(f"Fetched commit {sha[:7]} diff: {len(response.text)} bytes")
        return response.text
    
    def post_pr_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        commit_sha: str,
        path: str,
        line: int,
        message: str
    ) -> bool:
        """Post inline comment on PR."""
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/comments"
        
        payload = {
            "body": message,
            "commit_id": commit_sha,
            "path": path,
            "line": line,
            "side": "RIGHT"
        }
        
        try:
            response = self._make_request("POST", url, json=payload)
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
        owner: str,
        repo: str,
        sha: str,
        path: str,
        line: int,
        message: str
    ) -> bool:
        """Post comment on commit."""
        url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}/comments"
        
        payload = {
            "body": message,
            "path": path,
            "line": line
        }
        
        try:
            response = self._make_request("POST", url, json=payload)
            if response.status_code == 201:
                log_info(f"Posted commit comment on {path}:{line}")
                return True
            else:
                log_error(f"Failed to post commit comment: {response.status_code}")
                return False
        except Exception as e:
            log_error(f"Error posting commit comment: {e}")
            return False
    
    def create_check_run(
        self,
        owner: str,
        repo: str,
        sha: str,
        name: str,
        conclusion: str,
        title: str,
        summary: str
    ) -> bool:
        """Create check run with review summary."""
        url = f"https://api.github.com/repos/{owner}/{repo}/check-runs"
        
        payload = {
            "name": name,
            "head_sha": sha,
            "status": "completed",
            "conclusion": conclusion,  # success, failure, neutral
            "output": {
                "title": title,
                "summary": summary
            }
        }
        
        try:
            response = self._make_request("POST", url, json=payload)
            if response.status_code == 201:
                log_info(f"Created check run: {name}")
                return True
            else:
                log_error(f"Failed to create check run: {response.status_code}")
                return False
        except Exception as e:
            log_error(f"Error creating check run: {e}")
            return False
