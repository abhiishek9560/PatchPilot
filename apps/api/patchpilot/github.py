from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol

from .models import AgentRun
from .product_store import SQLiteProductStore


def verify_webhook_signature(body: bytes, signature: str, secret: str) -> bool:
    if not signature.startswith("sha256=") or not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def process_webhook_event(store: SQLiteProductStore, event_name: str, payload: dict) -> None:
    """Project signed GitHub events into PatchPilot's queryable product tables."""
    installation = payload.get("installation")
    if event_name == "installation" and installation:
        action = payload.get("action", "created")
        store.upsert_installation(
            installation,
            status="deleted" if action == "deleted" else "active",
        )
        for repository in payload.get("repositories", []):
            store.upsert_repository(int(installation["id"]), repository, action != "deleted")
        return

    if installation:
        store.upsert_installation(installation)

    if event_name == "installation_repositories" and installation:
        for repository in payload.get("repositories_added", []):
            store.upsert_repository(int(installation["id"]), repository)
        for repository in payload.get("repositories_removed", []):
            store.upsert_repository(int(installation["id"]), repository, active=False)
        return

    if event_name == "issues" and installation:
        repository = payload.get("repository") or {}
        issue = payload.get("issue") or {}
        if repository.get("id") and issue.get("number"):
            store.upsert_repository(int(installation["id"]), repository)
            store.upsert_issue(repository, issue)


@dataclass(frozen=True, slots=True)
class DraftPullRequest:
    url: str
    number: int
    title: str


class Publisher(Protocol):
    def create_draft_pull_request(self, run: AgentRun) -> DraftPullRequest: ...


class DemoPublisher:
    def create_draft_pull_request(self, run: AgentRun) -> DraftPullRequest:
        return DraftPullRequest(
            url=f"https://github.com/{run.issue.repository}/pull/demo-{run.id[:8]}",
            number=201,
            title=f"Fix #{run.issue.number}: {run.issue.title}",
        )
