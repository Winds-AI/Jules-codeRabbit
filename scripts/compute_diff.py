#!/usr/bin/env python3
"""Compute git diff for the current GitHub event."""

import argparse
import subprocess
import sys
from pathlib import Path

from utils import get_event_context, log_error, log_info


def run_command(cmd: list[str]) -> str:
    """Execute shell command and return output."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        log_error(f"Command failed: {' '.join(cmd)}")
        log_error(f"stderr: {e.stderr}")
        raise


def compute_diff(context: dict) -> str:
    """Compute diff based on event type."""
    if context["is_pull_request"]:
        # For PRs, diff from base to head
        base_ref = context["base_ref"]
        head_ref = context["head_ref"]
        log_info(f"Computing PR diff: {base_ref}...{head_ref}")
        
        # Fetch base ref to ensure it exists
        try:
            run_command(["git", "fetch", "origin", base_ref])
        except subprocess.CalledProcessError:
            log_info(f"Could not fetch {base_ref}, using local ref")
        
        diff = run_command(["git", "diff", f"origin/{base_ref}...origin/{head_ref}"])
    else:
        # For push events, diff from before to after
        before_sha = context["before"]
        after_sha = context["after"]
        log_info(f"Computing push diff: {before_sha}...{after_sha}")
        
        if before_sha == "0000000000000000000000000000000000000000":
            # New branch, diff from empty tree
            diff = run_command(["git", "diff", "4b825dc642cb6eb9a060e54bf8d69288fbee4904", after_sha])
        else:
            diff = run_command(["git", "diff", before_sha, after_sha])
    
    return diff


def main():
    parser = argparse.ArgumentParser(description="Compute git diff for GitHub event")
    parser.add_argument("--event-path", default=None, help="Path to GitHub event JSON")
    parser.add_argument("--output", required=True, help="Output diff file path")
    
    args = parser.parse_args()
    
    try:
        context = get_event_context()
        log_info(f"Event: {context['event_name']}")
        
        diff = compute_diff(context)
        
        if not diff.strip():
            log_info("No changes detected in diff")
        else:
            log_info(f"Diff computed: {len(diff)} bytes")
        
        # Write diff to file
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            f.write(diff)
        
        log_info(f"Diff saved to {args.output}")
        
    except Exception as e:
        log_error(f"Failed to compute diff: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
