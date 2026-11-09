from __future__ import annotations

from pathlib import Path

from .github import Publisher
from .models import AgentRun, Issue, RunStatus, TERMINAL_STATUSES
from .planner import Planner
from .policy import ExecutionPolicy, PolicyViolation
from .repository import RepositoryWorkspace
from .store import RunStore


class InvalidTransition(RuntimeError):
    pass


class PatchPilotWorkflow:
    def __init__(
        self,
        store: RunStore,
        planner: Planner,
        publisher: Publisher,
        allowed_commands: tuple[str, ...] = ("python3", "git", "rg"),
        protected_paths: tuple[str, ...] = (
            ".git",
            ".github/workflows",
            ".env",
            "secrets",
            "infra",
            "terraform",
        ),
        max_changed_files: int = 5,
        max_patch_bytes: int = 30_000,
        timeout_seconds: int = 120,
    ) -> None:
        self.store = store
        self.planner = planner
        self.publisher = publisher
        self.allowed_commands = allowed_commands
        self.protected_paths = protected_paths
        self.max_changed_files = max_changed_files
        self.max_patch_bytes = max_patch_bytes
        self.timeout_seconds = timeout_seconds

    def create_run(self, issue: Issue, workspace: Path) -> AgentRun:
        run = AgentRun(issue=issue, workspace=str(workspace.resolve()))
        run.add_event("run_created", f"Issue #{issue.number} accepted for bounded investigation")
        self.store.save(run)
        return run

    def _workspace(self, run: AgentRun) -> RepositoryWorkspace:
        root = Path(run.workspace)
        policy = ExecutionPolicy(
            workspace_root=root,
            allowed_commands=self.allowed_commands,
            protected_paths=self.protected_paths,
            max_changed_files=self.max_changed_files,
            max_patch_bytes=self.max_patch_bytes,
        )
        return RepositoryWorkspace(root, policy, self.timeout_seconds)

    def _context(self, workspace: RepositoryWorkspace, files: list[str]) -> str:
        sections: list[str] = []
        for path in files[:20]:
            if not path.endswith((".py", ".md", ".toml", ".txt")):
                continue
            try:
                sections.append(f"--- {path} ---\n{workspace.read_text(path, 20_000)}")
            except (ValueError, OSError, PolicyViolation):
                continue
        return "\n".join(sections)[:80_000]

    def advance(self, run_id: str) -> AgentRun:
        run = self.store.get(run_id)
        if run.status in TERMINAL_STATUSES:
            return run
        workspace = self._workspace(run)
        try:
            if run.status == RunStatus.RECEIVED:
                run.set_status(RunStatus.INSPECTING, "Started scoped repository inspection")
                run.inspected_files = workspace.list_files()
                run.add_event(
                    "tool_result",
                    f"Inspected {len(run.inspected_files)} repository files",
                    metadata={"files": run.inspected_files[:30]},
                )

            elif run.status == RunStatus.INSPECTING:
                result = workspace.run(
                    ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]
                )
                run.reproduction = result
                if result.passed:
                    raise InvalidTransition("Issue could not be reproduced; baseline tests passed")
                run.set_status(RunStatus.REPRODUCED, "Reproduced the reported defect")
                run.add_event(
                    "command_finished",
                    "Baseline verification failed as expected",
                    metadata={"exit_code": result.exit_code, "duration_ms": result.duration_ms},
                )

            elif run.status == RunStatus.REPRODUCED:
                context = self._context(workspace, run.inspected_files)
                run.plan = self.planner.create_plan(run, context)
                run.set_status(
                    RunStatus.AWAITING_PLAN_APPROVAL,
                    "Repair plan prepared; waiting for human approval",
                )
                run.add_event(
                    "approval_required",
                    "Human approval is required before any file is modified",
                    metadata={"approval": "plan"},
                )

            elif run.status == RunStatus.PATCHING:
                context = self._context(workspace, run.inspected_files)
                run.patch = self.planner.create_patch(run, context)
                changed = workspace.apply_patch(run.patch.unified_diff)
                run.set_status(RunStatus.VERIFYING, "Applied approved bounded patch")
                run.add_event(
                    "patch_applied",
                    f"Changed {len(changed)} allowed file(s)",
                    metadata={"files": changed},
                )

            elif run.status == RunStatus.VERIFYING:
                commands = run.plan.verification_commands if run.plan else []
                if not commands:
                    raise InvalidTransition("Approved plan has no verification commands")
                run.verification = [workspace.run(command) for command in commands]
                if not all(result.passed for result in run.verification):
                    raise InvalidTransition("Patched repository failed verification")
                run.set_status(RunStatus.REVIEWING, "All configured verification commands passed")

            elif run.status == RunStatus.REVIEWING:
                if run.patch is None:
                    raise InvalidTransition("No patch exists for review")
                changed = workspace.policy.validate_patch(run.patch.unified_diff)
                expected = set(run.plan.expected_files if run.plan else [])
                if not set(changed).issubset(expected):
                    raise PolicyViolation("Patch changes files outside the approved plan")
                run.set_status(
                    RunStatus.AWAITING_PUBLISH_APPROVAL,
                    "Policy and evidence review passed; draft PR approval required",
                )
                run.add_event(
                    "approval_required",
                    "Human approval is required before creating a draft pull request",
                    metadata={"approval": "publish"},
                )

            else:
                raise InvalidTransition(f"Run is paused in state: {run.status.value}")

        except (PolicyViolation, InvalidTransition, RuntimeError, OSError) as exc:
            run.failure = str(exc)
            run.set_status(RunStatus.FAILED, f"Failed safely: {exc}")
        self.store.save(run)
        return run

    def approve(self, run_id: str, approval: str, actor: str) -> AgentRun:
        run = self.store.get(run_id)
        if approval == "plan" and run.status == RunStatus.AWAITING_PLAN_APPROVAL:
            run.plan_approved_by = actor
            run.add_event("approval_granted", "Repair plan approved", actor, {"approval": "plan"})
            run.set_status(RunStatus.PATCHING, "Approval recorded; patching may begin")
        elif approval == "publish" and run.status == RunStatus.AWAITING_PUBLISH_APPROVAL:
            run.publish_approved_by = actor
            run.add_event(
                "approval_granted",
                "Draft PR publication approved",
                actor,
                {"approval": "publish"},
            )
            pull_request = self.publisher.create_draft_pull_request(run)
            run.pr_url = pull_request.url
            run.set_status(RunStatus.COMPLETED, "Draft pull request created")
            run.add_event(
                "draft_pr_created",
                f"Created draft pull request #{pull_request.number}",
                metadata={"url": pull_request.url},
            )
        else:
            raise InvalidTransition(
                f"Cannot approve {approval!r} while run is {run.status.value!r}"
            )
        self.store.save(run)
        return run

    def reject(self, run_id: str, actor: str, reason: str) -> AgentRun:
        run = self.store.get(run_id)
        if run.status not in {
            RunStatus.AWAITING_PLAN_APPROVAL,
            RunStatus.AWAITING_PUBLISH_APPROVAL,
        }:
            raise InvalidTransition(f"Run is not awaiting approval: {run.status.value}")
        run.add_event("approval_rejected", reason, actor)
        run.set_status(RunStatus.REJECTED, "Human reviewer rejected the run")
        self.store.save(run)
        return run

    def run_until_pause(self, run_id: str) -> AgentRun:
        while True:
            run = self.store.get(run_id)
            if run.status in TERMINAL_STATUSES or run.status in {
                RunStatus.AWAITING_PLAN_APPROVAL,
                RunStatus.AWAITING_PUBLISH_APPROVAL,
            }:
                return run
            self.advance(run_id)

