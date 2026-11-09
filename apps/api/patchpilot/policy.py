from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class PolicyViolation(ValueError):
    """Raised when a proposed side effect violates the V1 security contract."""


SHELL_META = re.compile(r"[;&|`$<>\n\r]")


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    workspace_root: Path
    allowed_commands: tuple[str, ...]
    protected_paths: tuple[str, ...]
    max_changed_files: int = 5
    max_patch_bytes: int = 30_000

    def resolve_path(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise PolicyViolation(f"Path escapes workspace: {relative_path}")
        normalized = candidate.as_posix()
        if normalized.startswith("./"):
            normalized = normalized[2:]
        for protected in self.protected_paths:
            protected_normalized = protected.strip("/")
            if normalized == protected_normalized or normalized.startswith(protected_normalized + "/"):
                raise PolicyViolation(f"Protected path: {relative_path}")
        root = self.workspace_root.resolve()
        resolved = (root / candidate).resolve()
        if root != resolved and root not in resolved.parents:
            raise PolicyViolation(f"Resolved path escapes workspace: {relative_path}")
        return resolved

    def validate_command(self, argv: Iterable[str]) -> list[str]:
        command = [str(part) for part in argv]
        if not command:
            raise PolicyViolation("Empty command")
        executable = Path(command[0]).name
        if executable not in self.allowed_commands:
            raise PolicyViolation(f"Command is not allowlisted: {executable}")
        for argument in command:
            if SHELL_META.search(argument):
                raise PolicyViolation(f"Shell metacharacter rejected in argument: {argument!r}")
        if executable == "git" and len(command) > 1 and command[1] not in {
            "apply",
            "diff",
            "status",
            "rev-parse",
        }:
            raise PolicyViolation(f"Git subcommand is not allowed: {command[1]}")
        return command

    def validate_patch(self, unified_diff: str) -> list[str]:
        encoded = unified_diff.encode("utf-8")
        if len(encoded) > self.max_patch_bytes:
            raise PolicyViolation(
                f"Patch size {len(encoded)} exceeds limit {self.max_patch_bytes}"
            )
        files: set[str] = set()
        for prefix, path in re.findall(r"^(---|\+\+\+)\s+(?:[ab]/)?([^\t\n]+)", unified_diff, re.M):
            del prefix
            if path == "/dev/null":
                continue
            self.resolve_path(path)
            files.add(path)
        if not files:
            raise PolicyViolation("Patch contains no changed files")
        if len(files) > self.max_changed_files:
            raise PolicyViolation(
                f"Patch changes {len(files)} files; limit is {self.max_changed_files}"
            )
        return sorted(files)
