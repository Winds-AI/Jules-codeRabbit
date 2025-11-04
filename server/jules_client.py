"""Jules API client for code review."""

import time
import requests
from typing import Dict, Any, List
from pathlib import Path

from utils import log_info, log_error, log_debug


class JulesReviewClient:
    """Client for Jules/Gemini code review API."""
    
    # Using Gemini API endpoint (Jules is based on Gemini)
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    MODEL = "gemini-2.0-flash-exp"
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
    
    def call_review_api(self, prompt: str) -> Dict[str, Any]:
        """Call Jules/Gemini API with retry logic."""
        url = f"{self.BASE_URL}/{self.MODEL}:generateContent?key={self.api_key}"
        
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 8192
            }
        }
        
        for attempt in range(self.MAX_RETRIES):
            try:
                log_info(f"Calling Jules API (attempt {attempt + 1}/{self.MAX_RETRIES})")
                response = self.session.post(url, json=payload, timeout=120)
                
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
        """Parse Jules response into structured findings."""
        findings = []
        
        try:
            # Extract text from Gemini response
            if "candidates" not in response or not response["candidates"]:
                log_error("No candidates in response")
                return findings
            
            text = response["candidates"][0]["content"]["parts"][0]["text"]
            log_debug(f"Response text: {text[:500]}...")
            
            # Parse structured findings from response
            # Expected format: JSON array or structured text
            import json
            import re
            
            # Try to extract JSON from response
            json_match = re.search(r'\[[\s\S]*\]', text)
            if json_match:
                findings_data = json.loads(json_match.group())
                for item in findings_data:
                    findings.append({
                        "file": item.get("file", "unknown"),
                        "line": item.get("line", 0),
                        "severity": item.get("severity", "MEDIUM"),
                        "message": item.get("message", ""),
                        "suggestion": item.get("suggestion", "")
                    })
            else:
                # Fallback: parse text format
                log_info("No JSON found, using text parsing")
                # This is a simplified parser - enhance based on actual response format
        
        except Exception as e:
            log_error(f"Error parsing findings: {e}")
        
        return findings


def load_prompt_template() -> str:
    """Load prompt template from config."""
    # Look for template in parent config dir
    template_path = Path(__file__).parent.parent / "config" / "prompt-template.md"
    
    if not template_path.exists():
        log_error(f"Prompt template not found: {template_path}")
        raise FileNotFoundError(f"Prompt template not found: {template_path}")
    
    with open(template_path) as f:
        return f.read()


def build_prompt(diff: str, context: Dict[str, Any]) -> str:
    """Build review prompt from template and diff."""
    template = load_prompt_template()
    
    # Truncate diff if too large (50KB limit)
    if len(diff) > 50000:
        log_info(f"Diff too large ({len(diff)} bytes), truncating...")
        diff = diff[:50000] + "\n\n[... diff truncated due to size ...]"
    
    prompt = template.replace("{DIFF_CONTENT}", diff)
    
    # Add context metadata
    repo = context.get("repo", "unknown")
    prompt += f"\n\n---\n**Repository:** {repo}\n"
    
    return prompt
