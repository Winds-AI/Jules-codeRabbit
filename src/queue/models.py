"""Data models for review queue jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field


class RepositoryInfo(BaseModel):
    id: int | None = None
    full_name: str
    owner: str | None = None
    name: str | None = None


class PushPayload(BaseModel):
    event_type: Literal["push"] = "push"
    installation_id: int
    repository: RepositoryInfo
    ref: str | None = None
    before: str | None = None
    after: str | None = None
    commits: list[str] = Field(default_factory=list)
    pusher: Dict[str, Any] = Field(default_factory=dict)
    compare: str | None = None


class PullRequestEndpoint(BaseModel):
    ref: str | None = None
    sha: str | None = None


class PullRequestInfo(BaseModel):
    number: int
    title: str | None = None
    url: str | None = None
    head: PullRequestEndpoint = Field(default_factory=PullRequestEndpoint)
    base: PullRequestEndpoint = Field(default_factory=PullRequestEndpoint)


class PullRequestPayload(BaseModel):
    event_type: Literal["pull_request"] = "pull_request"
    installation_id: int
    repository: RepositoryInfo
    action: str
    pull_request: PullRequestInfo
    sender: Dict[str, Any] = Field(default_factory=dict)


class ReviewJob(BaseModel):
    delivery_id: str
    event: Literal["push", "pull_request"]
    payload: PushPayload | PullRequestPayload
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

