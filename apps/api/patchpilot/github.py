from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol

from .models import AgentRun


def verify_webhook_signature(body: bytes, signature: str, secret: str) -> bool:
    if not signature.startswith("sha256=") or not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


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

