from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from .database import PostgresConnection
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

    @staticmethod
    def _integrity_error_class() -> type[Exception]:
        return sqlite3.IntegrityError

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
                    installation_id BIGINT PRIMARY KEY,
                    organization_id TEXT REFERENCES organizations(id),
                    account_login TEXT NOT NULL,
                    account_type TEXT NOT NULL,
                    repository_selection TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS repositories (
                    github_id BIGINT PRIMARY KEY,
                    installation_id BIGINT NOT NULL REFERENCES github_installations(installation_id),
                    full_name TEXT NOT NULL UNIQUE,
                    default_branch TEXT NOT NULL,
                    private INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS issues (
                    repository_id BIGINT NOT NULL REFERENCES repositories(github_id),
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
                CREATE TABLE IF NOT EXISTS work_items (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL REFERENCES organizations(id),
                    repository_id BIGINT NOT NULL REFERENCES repositories(github_id),
                    issue_number INTEGER NOT NULL,
                    requested_by TEXT NOT NULL REFERENCES users(id),
                    selection_mode TEXT NOT NULL CHECK(selection_mode IN ('manual', 'automatic')),
                    status TEXT NOT NULL,
                    plan_payload TEXT,
                    plan_version INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (repository_id, issue_number) REFERENCES issues(repository_id, number)
                );
                CREATE INDEX IF NOT EXISTS work_items_organization
                    ON work_items(organization_id, updated_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_work_item_per_issue
                    ON work_items(organization_id, repository_id, issue_number)
                    WHERE status NOT IN ('completed', 'rejected', 'failed', 'cancelled');
                CREATE TABLE IF NOT EXISTS plan_feedback (
                    id TEXT PRIMARY KEY,
                    work_item_id TEXT NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    plan_version INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS work_item_approvals (
                    id TEXT PRIMARY KEY,
                    work_item_id TEXT NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    stage TEXT NOT NULL CHECK(stage IN ('plan', 'publish')),
                    plan_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(work_item_id, stage, plan_version)
                );
                CREATE TABLE IF NOT EXISTS durable_jobs (
                    id TEXT PRIMARY KEY,
                    work_item_id TEXT NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('queued', 'leased', 'completed', 'failed')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS durable_jobs_claim
                    ON durable_jobs(status, available_at, created_at);
                """
            )

    @staticmethod
    def _user(row: Any) -> User:
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
            except self._integrity_error_class() as exc:
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
            inserted = connection.execute(
                """
                INSERT INTO webhook_deliveries VALUES (?, ?, 'processing', NULL, ?, NULL)
                ON CONFLICT(delivery_id) DO NOTHING
                """,
                (delivery_id, event_name, utc_now()),
            ).rowcount
        return bool(inserted)

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

    @staticmethod
    def _work_item(row: Any) -> dict:
        item = dict(row)
        plan_payload = item.pop("plan_payload")
        item["plan"] = json.loads(plan_payload) if plan_payload else None
        return item

    def assign_issue(
        self,
        user_id: str,
        repository_id: int,
        issue_number: int,
        selection_mode: str = "manual",
    ) -> dict:
        if selection_mode not in {"manual", "automatic"}:
            raise ValueError("Invalid issue selection mode")
        now = utc_now()
        with self._lock, self._connect() as connection:
            issue = connection.execute(
                """
                SELECT issues.*, github_installations.organization_id
                FROM issues JOIN repositories ON repositories.github_id = issues.repository_id
                JOIN github_installations USING (installation_id)
                JOIN organization_memberships
                  ON organization_memberships.organization_id = github_installations.organization_id
                WHERE issues.repository_id = ? AND issues.number = ?
                  AND organization_memberships.user_id = ? AND repositories.active = 1
                """,
                (repository_id, issue_number, user_id),
            ).fetchone()
            if issue is None:
                raise PermissionError("Issue is not available in your workspace")
            existing = connection.execute(
                """
                SELECT work_items.*, repositories.full_name, issues.title AS issue_title
                FROM work_items JOIN repositories ON repositories.github_id = work_items.repository_id
                JOIN issues ON issues.repository_id = work_items.repository_id
                  AND issues.number = work_items.issue_number
                WHERE work_items.organization_id = ? AND work_items.repository_id = ?
                  AND work_items.issue_number = ?
                  AND work_items.status NOT IN ('completed', 'rejected', 'failed', 'cancelled')
                """,
                (issue["organization_id"], repository_id, issue_number),
            ).fetchone()
            if existing:
                return self._work_item(existing)
            work_item_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO work_items VALUES (?, ?, ?, ?, ?, ?, 'queued_for_plan', NULL, 0, ?, ?)
                """,
                (
                    work_item_id,
                    issue["organization_id"],
                    repository_id,
                    issue_number,
                    user_id,
                    selection_mode,
                    now,
                    now,
                ),
            )
            self._enqueue_job(connection, work_item_id, "create_plan", {})
            row = connection.execute(
                """
                SELECT work_items.*, repositories.full_name, issues.title AS issue_title
                FROM work_items JOIN repositories ON repositories.github_id = work_items.repository_id
                JOIN issues ON issues.repository_id = work_items.repository_id
                  AND issues.number = work_items.issue_number
                WHERE work_items.id = ?
                """,
                (work_item_id,),
            ).fetchone()
        return self._work_item(row)

    def auto_assign_next_issue(self, user_id: str, organization_id: str) -> dict:
        self.require_membership(user_id, organization_id)
        with self._connect() as connection:
            candidate = connection.execute(
                """
                SELECT issues.repository_id, issues.number
                FROM issues JOIN repositories ON repositories.github_id = issues.repository_id
                JOIN github_installations USING (installation_id)
                WHERE github_installations.organization_id = ? AND repositories.active = 1
                  AND issues.state = 'open'
                  AND NOT EXISTS (
                    SELECT 1 FROM work_items
                    WHERE work_items.organization_id = github_installations.organization_id
                      AND work_items.repository_id = issues.repository_id
                      AND work_items.issue_number = issues.number
                      AND work_items.status NOT IN ('completed', 'rejected', 'failed', 'cancelled')
                  )
                ORDER BY
                  CASE WHEN issues.labels LIKE '%"bug"%' THEN 0 ELSE 1 END,
                  issues.updated_at DESC
                LIMIT 1
                """,
                (organization_id,),
            ).fetchone()
        if candidate is None:
            raise LookupError("No unassigned open issue is available")
        return self.assign_issue(
            user_id,
            int(candidate["repository_id"]),
            int(candidate["number"]),
            selection_mode="automatic",
        )

    def _enqueue_job(
        self, connection: Any, work_item_id: str, kind: str, payload: dict
    ) -> str:
        job_id = str(uuid4())
        now = utc_now()
        connection.execute(
            """
            INSERT INTO durable_jobs(
                id, work_item_id, kind, payload, status, attempts, available_at,
                lease_owner, lease_expires_at, last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'queued', 0, ?, NULL, NULL, NULL, ?, ?)
            """,
            (job_id, work_item_id, kind, json.dumps(payload), now, now, now),
        )
        return job_id

    def list_work_items(self, user_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT work_items.*, repositories.full_name, issues.title AS issue_title
                FROM work_items JOIN repositories ON repositories.github_id = work_items.repository_id
                JOIN issues ON issues.repository_id = work_items.repository_id
                  AND issues.number = work_items.issue_number
                JOIN organization_memberships
                  ON organization_memberships.organization_id = work_items.organization_id
                WHERE organization_memberships.user_id = ?
                ORDER BY work_items.updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._work_item(row) for row in rows]

    def get_work_item(self, user_id: str, work_item_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT work_items.*, repositories.full_name, issues.title AS issue_title
                FROM work_items JOIN repositories ON repositories.github_id = work_items.repository_id
                JOIN issues ON issues.repository_id = work_items.repository_id
                  AND issues.number = work_items.issue_number
                JOIN organization_memberships
                  ON organization_memberships.organization_id = work_items.organization_id
                WHERE work_items.id = ? AND organization_memberships.user_id = ?
                """,
                (work_item_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError("Unknown or unauthorized work item")
        item = self._work_item(row)
        item["feedback"] = self.list_plan_feedback(user_id, work_item_id)
        return item

    def list_plan_feedback(self, user_id: str, work_item_id: str) -> list[dict]:
        self.get_work_item_authorization(user_id, work_item_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT plan_feedback.id, plan_feedback.plan_version, plan_feedback.message,
                       plan_feedback.created_at, users.display_name AS author
                FROM plan_feedback JOIN users ON users.id = plan_feedback.user_id
                WHERE plan_feedback.work_item_id = ? ORDER BY plan_feedback.created_at
                """,
                (work_item_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_work_item_authorization(self, user_id: str, work_item_id: str) -> Any:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT work_items.* FROM work_items JOIN organization_memberships
                  ON organization_memberships.organization_id = work_items.organization_id
                WHERE work_items.id = ? AND organization_memberships.user_id = ?
                """,
                (work_item_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError("Unknown or unauthorized work item")
        return row

    def record_plan(self, work_item_id: str, plan: dict) -> dict:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT plan_version FROM work_items WHERE id = ?", (work_item_id,)
            ).fetchone()
            if row is None:
                raise KeyError("Unknown work item")
            version = int(row["plan_version"]) + 1
            connection.execute(
                """
                UPDATE work_items SET status = 'awaiting_plan_approval', plan_payload = ?,
                    plan_version = ?, updated_at = ? WHERE id = ?
                """,
                (json.dumps(plan), version, utc_now(), work_item_id),
            )
        return {"work_item_id": work_item_id, "plan_version": version, "plan": plan}

    def submit_plan_feedback(self, user_id: str, work_item_id: str, message: str) -> dict:
        message = " ".join(message.strip().split())
        if len(message) < 3 or len(message) > 2000:
            raise ValueError("Feedback must contain 3 to 2000 characters")
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT work_items.* FROM work_items JOIN organization_memberships
                  ON organization_memberships.organization_id = work_items.organization_id
                WHERE work_items.id = ? AND organization_memberships.user_id = ?
                """,
                (work_item_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown or unauthorized work item")
            if row["status"] != "awaiting_plan_approval":
                raise ValueError("Plan feedback is only accepted while plan approval is pending")
            feedback_id = str(uuid4())
            now = utc_now()
            connection.execute(
                "INSERT INTO plan_feedback VALUES (?, ?, ?, ?, ?, ?)",
                (feedback_id, work_item_id, user_id, row["plan_version"], message, now),
            )
            connection.execute(
                "UPDATE work_items SET status = 'queued_for_plan_revision', updated_at = ? WHERE id = ?",
                (now, work_item_id),
            )
            self._enqueue_job(
                connection,
                work_item_id,
                "revise_plan",
                {"feedback_id": feedback_id, "plan_version": row["plan_version"]},
            )
        return {"id": feedback_id, "message": message, "created_at": now}

    def approve_work_item(self, user_id: str, work_item_id: str, stage: str) -> dict:
        expected_status = {
            "plan": "awaiting_plan_approval",
            "publish": "awaiting_publish_approval",
        }.get(stage)
        if expected_status is None:
            raise ValueError("Approval stage must be plan or publish")
        next_status = "queued_for_patch" if stage == "plan" else "queued_for_publish"
        job_kind = "create_patch" if stage == "plan" else "publish_draft_pr"
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT work_items.* FROM work_items JOIN organization_memberships
                  ON organization_memberships.organization_id = work_items.organization_id
                WHERE work_items.id = ? AND organization_memberships.user_id = ?
                """,
                (work_item_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown or unauthorized work item")
            if row["status"] != expected_status:
                raise ValueError(f"Cannot approve {stage} while work item is {row['status']}")
            approval_id = str(uuid4())
            now = utc_now()
            connection.execute(
                "INSERT INTO work_item_approvals VALUES (?, ?, ?, ?, ?, ?)",
                (approval_id, work_item_id, user_id, stage, row["plan_version"], now),
            )
            connection.execute(
                "UPDATE work_items SET status = ?, updated_at = ? WHERE id = ?",
                (next_status, now, work_item_id),
            )
            self._enqueue_job(connection, work_item_id, job_kind, {})
        return {"id": approval_id, "stage": stage, "created_at": now}

    def claim_job(self, worker_id: str, lease_seconds: int = 300) -> dict | None:
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        lease_expires = (now + timedelta(seconds=lease_seconds)).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM durable_jobs
                WHERE (status = 'queued' AND available_at <= ?)
                   OR (status = 'leased' AND lease_expires_at <= ?)
                ORDER BY created_at LIMIT 1
                """,
                (now_text, now_text),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE durable_jobs SET status = 'leased', attempts = attempts + 1,
                    lease_owner = ?, lease_expires_at = ?, updated_at = ? WHERE id = ?
                """,
                (worker_id, lease_expires, now_text, row["id"]),
            )
            result = dict(row)
            result.update(
                status="leased",
                attempts=int(row["attempts"]) + 1,
                lease_owner=worker_id,
                lease_expires_at=lease_expires,
            )
            result["payload"] = json.loads(result["payload"])
            return result

    def complete_job(self, job_id: str, worker_id: str) -> None:
        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE durable_jobs SET status = 'completed', lease_owner = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE id = ? AND status = 'leased' AND lease_owner = ?
                """,
                (utc_now(), job_id, worker_id),
            ).rowcount
        if not updated:
            raise PermissionError("Worker does not own this job lease")

    def fail_job(
        self, job_id: str, worker_id: str, error: str, retry_delay_seconds: int = 30
    ) -> bool:
        available = (datetime.now(timezone.utc) + timedelta(seconds=retry_delay_seconds)).isoformat()
        with self._connect() as connection:
            job = connection.execute(
                "SELECT attempts FROM durable_jobs WHERE id = ? AND lease_owner = ?",
                (job_id, worker_id),
            ).fetchone()
            if job is None:
                raise PermissionError("Worker does not own this job lease")
            final = int(job["attempts"]) >= 3
            connection.execute(
                """
                UPDATE durable_jobs SET status = ?, available_at = ?, lease_owner = NULL,
                    lease_expires_at = NULL, last_error = ?, updated_at = ? WHERE id = ?
                """,
                ("failed" if final else "queued", available, error[:1000], utc_now(), job_id),
            )
            if final:
                connection.execute(
                    """
                    UPDATE work_items SET status = 'failed', updated_at = ?
                    WHERE id = (SELECT work_item_id FROM durable_jobs WHERE id = ?)
                    """,
                    (utc_now(), job_id),
                )
        return final


class PostgresProductStore(SQLiteProductStore):
    """Production product store backed by a standard PostgreSQL DATABASE_URL."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> PostgresConnection:
        return PostgresConnection(self.database_url)

    @staticmethod
    def _integrity_error_class() -> type[Exception]:
        import psycopg

        return psycopg.IntegrityError

    def claim_job(self, worker_id: str, lease_seconds: int = 300) -> dict | None:
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        lease_expires = (now + timedelta(seconds=lease_seconds)).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM durable_jobs
                WHERE (status = 'queued' AND available_at <= ?)
                   OR (status = 'leased' AND lease_expires_at <= ?)
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                (now_text, now_text),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE durable_jobs SET status = 'leased', attempts = attempts + 1,
                    lease_owner = ?, lease_expires_at = ?, updated_at = ? WHERE id = ?
                """,
                (worker_id, lease_expires, now_text, row["id"]),
            )
            result = dict(row)
            result.update(
                status="leased",
                attempts=int(row["attempts"]) + 1,
                lease_owner=worker_id,
                lease_expires_at=lease_expires,
            )
            result["payload"] = json.loads(result["payload"])
            return result
