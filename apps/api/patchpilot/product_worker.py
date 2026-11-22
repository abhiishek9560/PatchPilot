from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .github import GitHubAppClient
from .models import AgentRun, Issue, RepairPlan
from .planner import Planner
from .policy import ExecutionPolicy, PolicyViolation
from .product_store import SQLiteProductStore
from .repository import RepositoryWorkspace


class GitCommandError(RuntimeError):
    """A sanitized Git failure that never includes an installation token."""


class GitRepositoryManager:
    """Clone and publish a single repository with an in-memory installation token."""

    def __init__(self, author_name: str, author_email: str, timeout_seconds: int = 120) -> None:
        self.author_name = author_name
        self.author_email = author_email
        self.timeout_seconds = timeout_seconds

    def _run(
        self,
        argv: list[str],
        *,
        cwd: Path,
        token: str | None = None,
        commit_date: str | None = None,
    ) -> str:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "GIT_TERMINAL_PROMPT": "0",
        }
        askpass: Path | None = None
        if token:
            askpass = cwd / ".patchpilot-askpass.sh"
            askpass.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                "  *Username*) printf '%s\\n' \"$PATCHPILOT_GIT_USERNAME\" ;;\n"
                "  *) printf '%s\\n' \"$PATCHPILOT_GIT_TOKEN\" ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            askpass.chmod(0o700)
            env.update(
                {
                    "GIT_ASKPASS": str(askpass),
                    "PATCHPILOT_GIT_USERNAME": "x-access-token",
                    "PATCHPILOT_GIT_TOKEN": token,
                }
            )
        if commit_date:
            env["GIT_AUTHOR_DATE"] = commit_date
            env["GIT_COMMITTER_DATE"] = commit_date
        try:
            result = subprocess.run(
                argv,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
                check=False,
            )
        finally:
            if askpass is not None:
                askpass.unlink(missing_ok=True)
        if result.returncode:
            detail = (result.stderr or result.stdout or "unknown Git error")[-2_000:]
            if token:
                detail = detail.replace(token, "[REDACTED]")
            raise GitCommandError(detail.strip())
        return result.stdout.strip()

    def clone(
        self,
        *,
        token: str,
        repository: str,
        branch: str,
        destination: Path,
    ) -> None:
        clone_url = f"https://github.com/{repository}.git"
        self._run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--branch",
                branch,
                clone_url,
                str(destination),
            ],
            cwd=destination.parent,
            token=token,
        )

    def commit_and_push(
        self,
        *,
        repository_root: Path,
        token: str,
        branch: str,
        message: str,
        commit_date: str,
    ) -> str:
        self._run(["git", "checkout", "-b", branch], cwd=repository_root)
        self._run(["git", "add", "--all"], cwd=repository_root)
        self._run(
            [
                "git",
                "-c",
                f"user.name={self.author_name}",
                "-c",
                f"user.email={self.author_email}",
                "commit",
                "-m",
                message,
            ],
            cwd=repository_root,
            commit_date=commit_date,
        )
        commit_sha = self._run(["git", "rev-parse", "HEAD"], cwd=repository_root)
        self._run(
            ["git", "push", "origin", f"HEAD:refs/heads/{branch}"],
            cwd=repository_root,
            token=token,
        )
        return commit_sha


class ProductJobHandlers:
    """Production handlers for issue planning, patching, and draft-PR publication."""

    _TEXT_SUFFIXES = {
        ".c",
        ".cc",
        ".cpp",
        ".css",
        ".go",
        ".h",
        ".html",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".mjs",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }

    def __init__(
        self,
        *,
        store: SQLiteProductStore,
        planner: Planner,
        github: GitHubAppClient,
        workspace_root: Path,
        allowed_commands: tuple[str, ...],
        protected_paths: tuple[str, ...],
        max_changed_files: int,
        max_patch_bytes: int,
        timeout_seconds: int,
        git_author_name: str,
        git_author_email: str,
        repository_manager: GitRepositoryManager | None = None,
    ) -> None:
        self.store = store
        self.planner = planner
        self.github = github
        self.workspace_root = workspace_root.resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.allowed_commands = allowed_commands
        self.protected_paths = protected_paths
        self.max_changed_files = max_changed_files
        self.max_patch_bytes = max_patch_bytes
        self.timeout_seconds = timeout_seconds
        self.repositories = repository_manager or GitRepositoryManager(
            git_author_name,
            git_author_email,
            timeout_seconds,
        )

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "create_plan": self.create_plan,
            "revise_plan": self.revise_plan,
            "create_patch": self.create_patch,
            "publish_draft_pr": self.publish_draft_pr,
        }

    def _workspace(self, root: Path) -> RepositoryWorkspace:
        policy = ExecutionPolicy(
            workspace_root=root,
            allowed_commands=self.allowed_commands,
            protected_paths=self.protected_paths,
            max_changed_files=self.max_changed_files,
            max_patch_bytes=self.max_patch_bytes,
        )
        return RepositoryWorkspace(root, policy, self.timeout_seconds)

    def _token(self, context: dict, permission: str) -> str:
        return self.github.installation_token(
            int(context["installation_id"]),
            repository_ids=[int(context["repository_id"])],
            permissions={"contents": permission},
        )

    def _clone(self, context: dict, parent: Path, permission: str = "read") -> Path:
        repository_root = parent / "repository"
        self.repositories.clone(
            token=self._token(context, permission),
            repository=context["full_name"],
            branch=context["default_branch"],
            destination=repository_root,
        )
        return repository_root

    @staticmethod
    def _run(context: dict, workspace: Path) -> AgentRun:
        run = AgentRun(
            issue=Issue(
                repository=context["full_name"],
                number=int(context["issue_number"]),
                title=context["issue_title"],
                body=context["issue_body"],
                default_branch=context["default_branch"],
            ),
            workspace=str(workspace),
        )
        if context.get("plan"):
            run.plan = RepairPlan(**context["plan"])
        return run

    def _repository_context(
        self,
        workspace: RepositoryWorkspace,
        preferred_files: list[str] | None = None,
    ) -> str:
        files = workspace.list_files(limit=300)
        preferred = [item for item in (preferred_files or []) if item in files]
        common = [
            item
            for item in files
            if Path(item).name.casefold()
            in {
                "readme.md",
                "pyproject.toml",
                "package.json",
                "go.mod",
                "cargo.toml",
                "pom.xml",
                "requirements.txt",
            }
        ]
        source = [
            item
            for item in files
            if Path(item).suffix.casefold() in self._TEXT_SUFFIXES
            and item not in preferred
            and item not in common
        ]
        selected = list(dict.fromkeys(preferred + common + source))[:45]
        sections = ["Repository file tree:\n" + "\n".join(files)]
        for path in selected:
            try:
                content = workspace.read_text(path, max_bytes=20_000)
            except (OSError, UnicodeError, ValueError, PolicyViolation):
                continue
            sections.append(f"--- {path} ---\n{content}")
            if sum(len(section) for section in sections) >= 100_000:
                break
        return "\n\n".join(sections)[:100_000]

    def _plan(self, job: dict, *, revision: bool) -> None:
        context = self.store.get_job_context(job["work_item_id"])
        with tempfile.TemporaryDirectory(
            prefix=f"plan-{context['id'][:8]}-", dir=self.workspace_root
        ) as temporary:
            repository_root = self._clone(context, Path(temporary))
            workspace = self._workspace(repository_root)
            evidence = self._repository_context(workspace)
            if revision:
                evidence += "\n\nCurrent plan:\n" + json.dumps(context["plan"], indent=2)
                evidence += "\n\nUser feedback:\n" + "\n".join(
                    f"- {entry['message']}" for entry in context["feedback"]
                )
            plan = self.planner.create_plan(self._run(context, repository_root), evidence)
            self.store.record_plan(context["id"], asdict(plan))

    def create_plan(self, job: dict) -> None:
        self._plan(job, revision=False)

    def revise_plan(self, job: dict) -> None:
        self._plan(job, revision=True)

    def create_patch(self, job: dict) -> None:
        context = self.store.get_job_context(job["work_item_id"])
        if not context.get("plan"):
            raise RuntimeError("Cannot create a patch without an approved plan")
        with tempfile.TemporaryDirectory(
            prefix=f"patch-{context['id'][:8]}-", dir=self.workspace_root
        ) as temporary:
            repository_root = self._clone(context, Path(temporary))
            workspace = self._workspace(repository_root)
            run = self._run(context, repository_root)
            evidence = self._repository_context(workspace, run.plan.expected_files)
            proposal = self.planner.create_patch(run, evidence)
            changed = workspace.apply_patch(proposal.unified_diff)
            proposal.changed_files = changed
            expected = set(run.plan.expected_files)
            if not set(changed).issubset(expected):
                raise PolicyViolation("Patch changes files outside the approved plan")
            check = workspace.run(["git", "diff", "--check"])
            if not check.passed:
                raise RuntimeError(check.stderr or check.stdout or "git diff --check failed")
            actual = workspace.run(["git", "diff", "--name-only"])
            actual_files = [line for line in actual.stdout.splitlines() if line]
            if set(actual_files) != set(changed):
                raise PolicyViolation("Applied patch differs from the reviewed patch scope")
            branch = f"patchpilot/issue-{context['issue_number']}-{context['id'][:8]}"
            self.store.record_patch_result(
                context["id"],
                branch_name=branch,
                patch=asdict(proposal),
                verification={
                    "mode": "static",
                    "passed": True,
                    "checks": [asdict(check)],
                    "changed_files": actual_files,
                    "note": (
                        "Patch policy and git diff checks passed. Repository code was not "
                        "executed on the shared API host."
                    ),
                },
            )

    def publish_draft_pr(self, job: dict) -> None:
        context = self.store.get_job_context(job["work_item_id"])
        artifact = context.get("artifact")
        if not artifact or not artifact.get("patch") or not artifact.get("branch_name"):
            raise RuntimeError("Cannot publish without an approved patch artifact")
        with tempfile.TemporaryDirectory(
            prefix=f"publish-{context['id'][:8]}-", dir=self.workspace_root
        ) as temporary:
            token = self._token(context, "write")
            repository_root = Path(temporary) / "repository"
            self.repositories.clone(
                token=token,
                repository=context["full_name"],
                branch=context["default_branch"],
                destination=repository_root,
            )
            workspace = self._workspace(repository_root)
            workspace.apply_patch(artifact["patch"]["unified_diff"])
            check = workspace.run(["git", "diff", "--check"])
            if not check.passed:
                raise RuntimeError(check.stderr or check.stdout or "git diff --check failed")
            title = f"Fix #{context['issue_number']}: {context['issue_title']}"[:240]
            commit_sha = self.repositories.commit_and_push(
                repository_root=repository_root,
                token=token,
                branch=artifact["branch_name"],
                message=title,
                commit_date=context["created_at"],
            )
            plan = context["plan"] or {}
            body = (
                "## PatchPilot draft\n\n"
                f"Closes #{context['issue_number']}\n\n"
                f"{plan.get('summary', 'Automated repair proposal')}\n\n"
                "### Validation\n\n"
                "- Human-approved repair plan\n"
                "- Bounded patch policy passed\n"
                "- `git diff --check` passed\n\n"
                "> This is a draft PR. Review and run the repository's trusted CI before merging."
            )
            pull_request = self.github.find_or_create_draft_pull_request(
                installation_id=int(context["installation_id"]),
                repository_id=int(context["repository_id"]),
                repository=context["full_name"],
                title=title,
                head=artifact["branch_name"],
                base=context["default_branch"],
                body=body,
            )
            self.store.record_pull_request(
                context["id"],
                commit_sha=commit_sha,
                pr_url=pull_request.url,
                pr_number=pull_request.number,
            )
