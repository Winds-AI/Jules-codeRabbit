#!/usr/bin/env python3
"""Call Jules API to review code changes."""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from utils import (
    get_event_context,
    load_json,
    log_debug,
    log_error,
    log_info,
    parse_diff_file,
    save_json,
)


class JulesReviewClient:
    """Client for Jules code review API."""
    
    BASE_URL = "https://api.google.com/v1"  # Placeholder; update with actual endpoint
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })
    
    def call_review_api(self, prompt: str) -> Dict[str, Any]:
        """Call Jules review API with retry logic."""
        url = f"{self.BASE_URL}/review"
        payload = {
            "prompt": prompt,
            "model": "jules-v1",
        }
        
        for attempt in range(self.MAX_RETRIES):
            try:
                log_info(f"Calling Jules API (attempt {attempt + 1}/{self.MAX_RETRIES})")
                response = self.session.post(url, json=payload, timeout=60)
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code in (429, 500, 502, 503):
                    if attempt < self.MAX_RETRIES - 1:
                        wait_time = self.RETRY_DELAY * (2 ** attempt)
                        log_info(f"Rate limited/server error. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise Exception(f"API error after retries: {response.status_code}")
                else:
                    raise Exception(f"API error: {response.status_code} - {response.text}")
            
            except requests.RequestException as e:
                if attempt < self.MAX_RETRIES - 1:
                    log_info(f"Request failed: {e}. Retrying...")
                    time.sleep(self.RETRY_DELAY)
                else:
                    raise Exception(f"Request failed after retries: {e}")
        
        raise Exception("Max retries exceeded")
    
    def parse_findings(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Jules response into standardized findings."""
        findings = []
        
        # Extract findings from response
        # This is a placeholder; adjust based on actual Jules API response format
        if "findings" in response:
            for finding in response["findings"]:
                findings.append({
                    "file": finding.get("file", "unknown"),
                    "line": finding.get("line", 0),
                    "severity": finding.get("severity", "MEDIUM"),
                    "message": finding.get("message", ""),
                    "suggestion": finding.get("suggestion", ""),
                })
        
        return findings


def load_prompt_template() -> str:
    """Load prompt template from config."""
    template_path = Path(__file__).parent.parent / "config" / "prompt-template.md"
    if not template_path.exists():
        log_error(f"Prompt template not found: {template_path}")
        raise FileNotFoundError(f"Prompt template not found: {template_path}")
    
    with open(template_path) as f:
        return f.read()


def build_prompt(diff: str, context: Dict[str, Any]) -> str:
    """Build review prompt from template and diff."""
    template = load_prompt_template()
    
    # Truncate diff if too large (rough limit: 50KB)
    if len(diff) > 50000:
        log_info(f"Diff too large ({len(diff)} bytes), truncating...")
        diff = diff[:50000] + "\n\n[... diff truncated due to size ...]"
    
    prompt = template.replace("{DIFF_CONTENT}", diff)
    
    # Add context metadata
    repo = context.get("repo", "unknown")
    prompt += f"\n\n---\n**Repository:** {repo}\n"
    
    return prompt


def main():
    parser = argparse.ArgumentParser(description="Run Jules code review")
    parser.add_argument("--diff", required=True, help="Path to diff file")
    parser.add_argument("--event-path", default=None, help="Path to GitHub event JSON")
    parser.add_argument("--output", required=True, help="Output findings JSON file")
    
    args = parser.parse_args()
    
    try:
        # Get API key
        api_key = os.getenv("JULES_API_KEY")
        if not api_key:
            raise ValueError("JULES_API_KEY environment variable not set")
        
        # Load diff and context
        diff = parse_diff_file(args.diff)
        context = get_event_context()
        
        if not diff.strip():
            log_info("No changes in diff, skipping review")
            findings = []
        else:
            # Build prompt
            prompt = build_prompt(diff, context)
            log_debug(f"Prompt length: {len(prompt)} chars")
            
            # Call Jules API
            client = JulesReviewClient(api_key)
            response = client.call_review_api(prompt)
            log_info("Jules API response received")
            
            # Parse findings
            findings = client.parse_findings(response)
            log_info(f"Parsed {len(findings)} findings")
        
        # Save findings
        output_data = {
            "context": context,
            "findings": findings,
            "timestamp": time.time(),
        }
        save_json(output_data, args.output)
        log_info(f"Findings saved to {args.output}")
        
    except Exception as e:
        log_error(f"Jules review failed: {e}")
        # Save empty findings to allow workflow to continue
        output_data = {
            "context": get_event_context(),
            "findings": [],
            "error": str(e),
            "timestamp": time.time(),
        }
        save_json(output_data, args.output)
        sys.exit(1)


if __name__ == "__main__":
    main()
