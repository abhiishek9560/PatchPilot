from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Callable, Protocol

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


GitHubTransport = Callable[[str, str, dict[str, str], dict | None], dict]
JWTEncoder = Callable[[dict, str], str]


class GitHubAppClient:
    """Trusted GitHub App boundary. Installation tokens live only in memory."""

    def __init__(
        self,
        app_id: str,
        private_key: str,
        *,
        api_url: str = "https://api.github.com",
        transport: GitHubTransport | None = None,
        jwt_encoder: JWTEncoder | None = None,
    ) -> None:
        if not app_id or not private_key:
            raise ValueError("GitHub App ID and private key are required")
        self.app_id = app_id
        self.private_key = private_key.replace("\\n", "\n")
        self.api_url = api_url.rstrip("/")
        self.transport = transport or self._httpx_transport
        self.jwt_encoder = jwt_encoder or self._jwt_encode

    @staticmethod
    def _jwt_encode(payload: dict, private_key: str) -> str:
        import jwt

        return jwt.encode(payload, private_key, algorithm="RS256")

    @staticmethod
    def _httpx_transport(
        method: str, url: str, headers: dict[str, str], payload: dict | None
    ) -> dict:
        import httpx

        with httpx.Client(timeout=20) as client:
            response = client.request(method, url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    def app_jwt(self, now: int | None = None) -> str:
        issued = int(time.time()) if now is None else now
        payload = {"iat": issued - 60, "exp": issued + 9 * 60, "iss": self.app_id}
        return self.jwt_encoder(payload, self.private_key)

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "PatchPilot",
        }

    def installation_token(
        self,
        installation_id: int,
        *,
        repository_ids: list[int] | None = None,
        permissions: dict[str, str] | None = None,
    ) -> str:
        payload: dict = {}
        if repository_ids:
            payload["repository_ids"] = repository_ids
        if permissions:
            payload["permissions"] = permissions
        response = self.transport(
            "POST",
            f"{self.api_url}/app/installations/{installation_id}/access_tokens",
            self._headers(self.app_jwt()),
            payload,
        )
        token = response.get("token")
        if not token:
            raise RuntimeError("GitHub did not return an installation access token")
        return str(token)

    def create_draft_pull_request(
        self,
        *,
        installation_id: int,
        repository_id: int,
        repository: str,
        title: str,
        head: str,
        base: str,
        body: str,
    ) -> DraftPullRequest:
        token = self.installation_token(
            installation_id,
            repository_ids=[repository_id],
            permissions={"contents": "write", "pull_requests": "write"},
        )
        response = self.transport(
            "POST",
            f"{self.api_url}/repos/{repository}/pulls",
            self._headers(token),
            {"title": title, "head": head, "base": base, "body": body, "draft": True},
        )
        return DraftPullRequest(
            url=str(response["html_url"]),
            number=int(response["number"]),
            title=str(response.get("title", title)),
        )


class Publisher(Protocol):
    def create_draft_pull_request(self, run: AgentRun) -> DraftPullRequest: ...


class DemoPublisher:
    def create_draft_pull_request(self, run: AgentRun) -> DraftPullRequest:
        return DraftPullRequest(
            url=f"https://github.com/{run.issue.repository}/pull/demo-{run.id[:8]}",
            number=201,
            title=f"Fix #{run.issue.number}: {run.issue.title}",
        )
