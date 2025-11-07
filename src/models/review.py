"""Shared data structures for review processing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(slots=True)
class FilePatch:
    path: str
    status: str
    additions: int
    deletions: int
    patch: str | None = None


@dataclass(slots=True)
class PushReviewContext:
    repository: str
    installation_id: int
    ref: str | None
    before: str | None
    after: str | None
    commits: List[str] = field(default_factory=list)
    files: List[FilePatch] = field(default_factory=list)
    compare_url: str | None = None


@dataclass(slots=True)
class PullRequestReviewContext:
    repository: str
    installation_id: int
    pull_number: int
    title: str | None
    head_sha: str | None
    base_sha: str | None
    head_ref: str | None = None
    files: List[FilePatch] = field(default_factory=list)
    url: str | None = None


ReviewContext = PushReviewContext | PullRequestReviewContext


@dataclass(slots=True)
class ReviewFinding:
    path: str
    start_line: int
    end_line: int | None
    message: str
    severity: str | None = None


@dataclass(slots=True)
class ReviewAnalysis:
    comments: List[ReviewFinding] = field(default_factory=list)
    summary: str | None = None

