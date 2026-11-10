from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in os.getenv(name, default).split(",") if part.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str = field(default_factory=lambda: os.getenv("PATCHPILOT_ENV", "development"))
    planner: str = field(default_factory=lambda: os.getenv("PATCHPILOT_PLANNER", "deterministic"))
    database_path: Path = field(
        default_factory=lambda: Path(os.getenv("PATCHPILOT_DATABASE_PATH", ".patchpilot/patchpilot.db"))
    )
    workspace_root: Path = field(
        default_factory=lambda: Path(os.getenv("PATCHPILOT_WORKSPACE_ROOT", ".patchpilot/workspaces"))
    )
    max_changed_files: int = field(
        default_factory=lambda: int(os.getenv("PATCHPILOT_MAX_CHANGED_FILES", "5"))
    )
    max_patch_bytes: int = field(
        default_factory=lambda: int(os.getenv("PATCHPILOT_MAX_PATCH_BYTES", "30000"))
    )
    command_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("PATCHPILOT_COMMAND_TIMEOUT_SECONDS", "120"))
    )
    allowed_commands: tuple[str, ...] = field(
        default_factory=lambda: _csv(
            "PATCHPILOT_ALLOWED_COMMANDS", "python,python3,pytest,ruff,mypy,git,rg"
        )
    )
    protected_paths: tuple[str, ...] = field(
        default_factory=lambda: _csv(
            "PATCHPILOT_PROTECTED_PATHS",
            ".git,.github/workflows,.env,secrets,infra,terraform",
        )
    )
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", ""))
    session_cookie_name: str = field(
        default_factory=lambda: os.getenv("PATCHPILOT_SESSION_COOKIE", "patchpilot_session")
    )
    session_lifetime_days: int = field(
        default_factory=lambda: int(os.getenv("PATCHPILOT_SESSION_DAYS", "14"))
    )
    github_app_slug: str = field(default_factory=lambda: os.getenv("GITHUB_APP_SLUG", ""))
    github_app_id: str = field(default_factory=lambda: os.getenv("GITHUB_APP_ID", ""))
    github_private_key: str = field(
        default_factory=lambda: os.getenv("GITHUB_PRIVATE_KEY", "").replace("\\n", "\n")
    )
    github_webhook_secret: str = field(
        default_factory=lambda: os.getenv("GITHUB_WEBHOOK_SECRET", "")
    )

    @property
    def secure_cookies(self) -> bool:
        return self.environment != "development"
