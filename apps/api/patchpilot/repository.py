from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from .models import CommandResult
from .policy import ExecutionPolicy


class RepositoryWorkspace:
    """Scoped repository tools for a dedicated clone or fixture copy."""

    def __init__(
        self,
        root: Path,
        policy: ExecutionPolicy,
        timeout_seconds: int = 120,
        output_limit: int = 20_000,
    ) -> None:
        self.root = root.resolve()
        self.policy = policy
        self.timeout_seconds = timeout_seconds
        self.output_limit = output_limit
        if self.policy.workspace_root.resolve() != self.root:
            raise ValueError("Policy and workspace roots must match")

    def list_files(self, limit: int = 200) -> list[str]:
        files: list[str] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(self.root).as_posix()
            try:
                self.policy.resolve_path(relative)
            except Exception:
                continue
            files.append(relative)
            if len(files) >= limit:
                break
        return files

    def read_text(self, relative_path: str, max_bytes: int = 100_000) -> str:
        path = self.policy.resolve_path(relative_path)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Not a readable file: {relative_path}")
        data = path.read_bytes()
        if len(data) > max_bytes:
            raise ValueError(f"File exceeds read limit: {relative_path}")
        return data.decode("utf-8", errors="replace")

    def run(self, argv: list[str]) -> CommandResult:
        command = self.policy.validate_command(argv)
        safe_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(self.root),
        }
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=self.root,
                env=safe_env,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
                check=False,
            )
            duration = int((time.monotonic() - started) * 1000)
            return CommandResult(
                argv=command,
                exit_code=completed.returncode,
                stdout=completed.stdout[-self.output_limit :],
                stderr=completed.stderr[-self.output_limit :],
                duration_ms=duration,
            )
        except subprocess.TimeoutExpired as exc:
            duration = int((time.monotonic() - started) * 1000)
            return CommandResult(
                argv=command,
                exit_code=124,
                stdout=(exc.stdout or "")[-self.output_limit :],
                stderr=(exc.stderr or "")[-self.output_limit :],
                duration_ms=duration,
                timed_out=True,
            )

    def apply_patch(self, unified_diff: str) -> list[str]:
        changed = self.policy.validate_patch(unified_diff)
        patch_file = self.root / ".patchpilot.diff"
        patch_file.write_text(unified_diff, encoding="utf-8")
        try:
            result = self.run(["git", "apply", "--whitespace=nowarn", ".patchpilot.diff"])
            if not result.passed:
                raise RuntimeError(f"Patch failed: {result.stderr or result.stdout}")
        finally:
            patch_file.unlink(missing_ok=True)
        return changed

