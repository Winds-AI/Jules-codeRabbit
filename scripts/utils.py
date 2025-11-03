"""Shared utilities for Jules code review workflow."""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def load_github_event() -> Dict[str, Any]:
    """Load GitHub Actions event payload."""
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if not event_path or not Path(event_path).exists():
        raise FileNotFoundError("GITHUB_EVENT_PATH not set or file not found")
    
    with open(event_path) as f:
        return json.load(f)


def get_event_context() -> Dict[str, Any]:
    """Extract relevant context from GitHub event."""
    event = load_github_event()
    
    context = {
        "event_name": os.getenv("GITHUB_EVENT_NAME", "unknown"),
        "repo": os.getenv("GITHUB_REPOSITORY", ""),
        "sha": os.getenv("GITHUB_SHA", ""),
        "ref": os.getenv("GITHUB_REF", ""),
        "actor": os.getenv("GITHUB_ACTOR", ""),
    }
    
    # Extract PR-specific context
    if "pull_request" in event:
        pr = event["pull_request"]
        context.update({
            "is_pull_request": True,
            "pull_number": pr["number"],
            "base_ref": pr["base"]["ref"],
            "head_ref": pr["head"]["ref"],
            "base_sha": pr["base"]["sha"],
            "head_sha": pr["head"]["sha"],
        })
    else:
        context.update({
            "is_pull_request": False,
            "before": event.get("before", ""),
            "after": event.get("after", ""),
        })
    
    return context


def parse_diff_file(diff_path: str) -> str:
    """Read and return diff file content."""
    if not Path(diff_path).exists():
        raise FileNotFoundError(f"Diff file not found: {diff_path}")
    
    with open(diff_path) as f:
        return f.read()


def save_json(data: Dict[str, Any], output_path: str) -> None:
    """Save data to JSON file."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)


def load_json(file_path: str) -> Dict[str, Any]:
    """Load JSON file."""
    if not Path(file_path).exists():
        raise FileNotFoundError(f"JSON file not found: {file_path}")
    
    with open(file_path) as f:
        return json.load(f)


def log_info(message: str) -> None:
    """Print info message."""
    print(f"[INFO] {message}", file=sys.stdout)


def log_error(message: str) -> None:
    """Print error message."""
    print(f"[ERROR] {message}", file=sys.stderr)


def log_debug(message: str) -> None:
    """Print debug message."""
    if os.getenv("DEBUG"):
        print(f"[DEBUG] {message}", file=sys.stdout)
