from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .models import utc_now
from .security import expires_at, issue_secret, secret_digest


@dataclass(frozen=True, slots=True)
class User:
    id: str
    email: str
    display_name: str
    created_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class Organization:
    id: str
    name: str
    slug: str
    role: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "slug": self.slug, "role": self.role}


class SQLiteProductStore:
    """Durable product/account data separate from mutable agent-run payloads."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS organizations (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS organization_memberships (
                    organization_id TEXT NOT NULL REFERENCES organizations(id),
                    user_id TEXT NOT NULL REFERENCES users(id),
                    role TEXT NOT NULL CHECK(role IN ('owner', 'member')),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (organization_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_digest TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_user_id ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS github_setup_states (
                    state_digest TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS github_installations (
                    installation_id INTEGER PRIMARY KEY,
                    organization_id TEXT REFERENCES organizations(id),
                    account_login TEXT NOT NULL,
                    account_type TEXT NOT NULL,
                    repository_selection TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS repositories (
                    github_id INTEGER PRIMARY KEY,
                    installation_id INTEGER NOT NULL REFERENCES github_installations(installation_id),
                    full_name TEXT NOT NULL UNIQUE,
                    default_branch TEXT NOT NULL,
                    private INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS issues (
                    repository_id INTEGER NOT NULL REFERENCES repositories(github_id),
                    number INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    state TEXT NOT NULL,
                    html_url TEXT NOT NULL,
                    author_login TEXT,
                    labels TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (repository_id, number)
                );
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    event_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    received_at TEXT NOT NULL,
                    processed_at TEXT
                );
                """
            )

    @staticmethod
    def _user(row: sqlite3.Row) -> User:
        return User(row["id"], row["email"], row["display_name"], row["created_at"])

    def register_user(
        self, email: str, display_name: str, password_hash: str
    ) -> tuple[User, Organization]:
        now = utc_now()
        user_id = str(uuid4())
        organization_id = str(uuid4())
        base_slug = "-".join(display_name.casefold().split()) or "workspace"
        slug = f"{base_slug[:40]}-{user_id[:8]}"
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                    (user_id, email, display_name, password_hash, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("An account with that email already exists") from exc
            connection.execute(
                "INSERT INTO organizations VALUES (?, ?, ?, ?)",
                (organization_id, f"{display_name}'s workspace", slug, now),
            )
            connection.execute(
                "INSERT INTO organization_memberships VALUES (?, ?, 'owner', ?)",
                (organization_id, user_id, now),
            )
        return (
            User(user_id, email, display_name, now),
            Organization(organization_id, f"{display_name}'s workspace", slug, "owner"),
        )

    def authenticate(self, email: str) -> tuple[User, str] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()
        if row is None:
            return None
        return self._user(row), row["password_hash"]

    def create_session(self, user_id: str, lifetime_days: int) -> str:
        raw, digest = issue_secret()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?)",
                (digest, user_id, expires_at(lifetime_days), utc_now()),
            )
        return raw

    def user_for_session(self, raw_token: str) -> User | None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT users.* FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_digest = ? AND sessions.expires_at > ?
                """,
                (secret_digest(raw_token), now),
            ).fetchone()
        return self._user(row) if row else None

    def delete_session(self, raw_token: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_digest = ?", (secret_digest(raw_token),)
            )

    def organizations_for_user(self, user_id: str) -> list[Organization]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT organizations.*, organization_memberships.role
                FROM organizations JOIN organization_memberships
                  ON organizations.id = organization_memberships.organization_id
                WHERE organization_memberships.user_id = ? ORDER BY organizations.created_at
                """,
                (user_id,),
            ).fetchall()
        return [Organization(row["id"], row["name"], row["slug"], row["role"]) for row in rows]

    def begin_github_setup(self, user_id: str, organization_id: str) -> str:
        self.require_membership(user_id, organization_id, role="owner")
        raw, digest = issue_secret()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO github_setup_states VALUES (?, ?, ?, ?, NULL, ?)",
                (digest, user_id, organization_id, expires_at(1), utc_now()),
            )
        return raw

    def require_membership(self, user_id: str, organization_id: str, role: str | None = None) -> None:
        query = "SELECT role FROM organization_memberships WHERE user_id = ? AND organization_id = ?"
        with self._connect() as connection:
            row = connection.execute(query, (user_id, organization_id)).fetchone()
        if row is None or (role is not None and row["role"] != role):
            raise PermissionError("You do not have permission for this workspace")

    def claim_github_installation(
        self, raw_state: str, installation_id: int, user_id: str
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as connection:
            state = connection.execute(
                """
                SELECT * FROM github_setup_states
                WHERE state_digest = ? AND user_id = ? AND used_at IS NULL AND expires_at > ?
                """,
                (secret_digest(raw_state), user_id, now),
            ).fetchone()
            if state is None:
                raise ValueError("GitHub setup state is invalid or expired")
            installation = connection.execute(
                "SELECT status FROM github_installations WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
            if installation is None or installation["status"] != "active":
                raise LookupError("Waiting for GitHub to verify this installation")
            connection.execute(
                "UPDATE github_installations SET organization_id = ? WHERE installation_id = ?",
                (state["organization_id"], installation_id),
            )
            connection.execute(
                "UPDATE github_setup_states SET used_at = ? WHERE state_digest = ?",
                (utc_now(), state["state_digest"]),
            )
        return installation_id

    def record_webhook_delivery(self, delivery_id: str, event_name: str) -> bool:
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO webhook_deliveries VALUES (?, ?, 'processing', NULL, ?, NULL)",
                    (delivery_id, event_name, utc_now()),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def finish_webhook_delivery(self, delivery_id: str, error: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE webhook_deliveries SET status = ?, error = ?, processed_at = ?
                   WHERE delivery_id = ?""",
                ("failed" if error else "processed", error, utc_now(), delivery_id),
            )

    def upsert_installation(self, payload: dict, status: str = "active") -> None:
        account = payload.get("account") or {}
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO github_installations(
                    installation_id, account_login, account_type, repository_selection, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(installation_id) DO UPDATE SET
                    account_login=excluded.account_login, account_type=excluded.account_type,
                    repository_selection=excluded.repository_selection, status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    int(payload["id"]), account.get("login", "unknown"),
                    account.get("type", "Unknown"), payload.get("repository_selection", "selected"),
                    status, utc_now(),
                ),
            )

    def upsert_repository(self, installation_id: int, payload: dict, active: bool = True) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO repositories VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(github_id) DO UPDATE SET
                    installation_id=excluded.installation_id, full_name=excluded.full_name,
                    default_branch=excluded.default_branch, private=excluded.private,
                    active=excluded.active, updated_at=excluded.updated_at
                """,
                (
                    int(payload["id"]), installation_id, payload["full_name"],
                    payload.get("default_branch", "main"), int(bool(payload.get("private"))),
                    int(active), utc_now(),
                ),
            )

    def upsert_issue(self, repository: dict, issue: dict) -> None:
        labels = [item.get("name", "") for item in issue.get("labels", [])]
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO issues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repository_id, number) DO UPDATE SET
                    title=excluded.title, body=excluded.body, state=excluded.state,
                    html_url=excluded.html_url, author_login=excluded.author_login,
                    labels=excluded.labels, updated_at=excluded.updated_at
                """,
                (
                    int(repository["id"]), int(issue["number"]), issue["title"],
                    issue.get("body") or "", issue.get("state", "open"), issue.get("html_url", ""),
                    (issue.get("user") or {}).get("login"), json.dumps(labels), utc_now(),
                ),
            )

    def list_repositories(self, user_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT repositories.*, github_installations.account_login
                FROM repositories
                JOIN github_installations USING (installation_id)
                JOIN organization_memberships
                  ON organization_memberships.organization_id = github_installations.organization_id
                WHERE organization_memberships.user_id = ? AND repositories.active = 1
                ORDER BY repositories.full_name
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_issues(self, user_id: str, repository_id: int | None = None) -> list[dict]:
        parameters: list[object] = [user_id]
        repository_filter = ""
        if repository_id is not None:
            repository_filter = " AND issues.repository_id = ?"
            parameters.append(repository_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT issues.*, repositories.full_name
                FROM issues JOIN repositories ON repositories.github_id = issues.repository_id
                JOIN github_installations USING (installation_id)
                JOIN organization_memberships
                  ON organization_memberships.organization_id = github_installations.organization_id
                WHERE organization_memberships.user_id = ?
                """ + repository_filter + " ORDER BY issues.updated_at DESC",
                parameters,
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["labels"] = json.loads(item["labels"])
            result.append(item)
        return result
