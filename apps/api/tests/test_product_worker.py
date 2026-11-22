from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patchpilot.github import DraftPullRequest, process_webhook_event  # noqa: E402
from patchpilot.job_worker import DurableJobWorker  # noqa: E402
from patchpilot.planner import DeterministicPlanner  # noqa: E402
from patchpilot.product_store import SQLiteProductStore  # noqa: E402
from patchpilot.product_worker import ProductJobHandlers  # noqa: E402
from patchpilot.security import hash_password  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class FakeGitHubClient:
    def __init__(self) -> None:
        self.pull_requests: list[dict] = []

    def installation_token(self, installation_id: int, **_kwargs: object) -> str:
        if installation_id != 7:
            raise AssertionError("unexpected installation")
        return "short-lived-test-token"

    def find_or_create_draft_pull_request(self, **kwargs: object) -> DraftPullRequest:
        self.pull_requests.append(dict(kwargs))
        return DraftPullRequest(
            url="https://github.com/acme/api/pull/17",
            number=17,
            title=str(kwargs["title"]),
        )


class LocalRepositoryManager:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.published: list[dict] = []

    @staticmethod
    def _git(root: Path, *argv: str) -> str:
        result = subprocess.run(
            ["git", *argv], cwd=root, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()

    def clone(self, *, destination: Path, **_kwargs: object) -> None:
        shutil.copytree(self.source, destination)
        self._git(destination, "init", "-q")
        self._git(destination, "config", "user.name", "PatchPilot Test")
        self._git(destination, "config", "user.email", "patchpilot@example.com")
        self._git(destination, "add", "--all")
        self._git(destination, "commit", "-qm", "baseline")

    def commit_and_push(self, **kwargs: object) -> str:
        repository_root = Path(str(kwargs["repository_root"]))
        changed = self._git(repository_root, "diff", "--name-only")
        self.published.append({**kwargs, "changed": changed})
        return "a" * 40


class ProductJobHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.store = SQLiteProductStore(root / "product.db")
        self.user, organization = self.store.register_user(
            "worker@example.com", "Worker Test", hash_password("a secure password")
        )
        state = self.store.begin_github_setup(self.user.id, organization.id)
        installation = {
            "id": 7,
            "account": {"login": "acme", "type": "Organization"},
            "repository_selection": "selected",
        }
        repository = {
            "id": 8,
            "full_name": "acme/api",
            "default_branch": "main",
            "private": True,
        }
        issue = {
            "number": 9,
            "title": "Email validator accepts incomplete domains",
            "body": "user@example should be rejected",
            "state": "open",
            "html_url": "https://github.com/acme/api/issues/9",
            "labels": [{"name": "bug"}],
        }
        process_webhook_event(
            self.store,
            "installation",
            {"action": "created", "installation": installation, "repositories": [repository]},
        )
        self.store.claim_github_installation(state, 7, self.user.id)
        process_webhook_event(
            self.store,
            "issues",
            {"installation": installation, "repository": repository, "issue": issue},
        )
        self.work_item = self.store.assign_issue(self.user.id, 8, 9)
        self.github = FakeGitHubClient()
        self.repositories = LocalRepositoryManager(PROJECT_ROOT / "fixtures" / "email-validator")
        handlers = ProductJobHandlers(
            store=self.store,
            planner=DeterministicPlanner(),
            github=self.github,  # type: ignore[arg-type]
            workspace_root=root / "workspaces",
            allowed_commands=("git",),
            protected_paths=(".git", ".github/workflows", ".env", "secrets"),
            max_changed_files=5,
            max_patch_bytes=30_000,
            timeout_seconds=30,
            git_author_name="PatchPilot Test",
            git_author_email="patchpilot@example.com",
            repository_manager=self.repositories,  # type: ignore[arg-type]
        )
        self.worker = DurableJobWorker(
            self.store,
            "product-worker",
            handlers.handlers,
            retry_delay_seconds=0,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_issue_reaches_human_review_then_draft_pull_request(self) -> None:
        self.assertTrue(self.worker.run_once())
        planned = self.store.get_work_item(self.user.id, self.work_item["id"])
        self.assertEqual(planned["status"], "awaiting_plan_approval")
        self.assertEqual(planned["plan_version"], 1)

        self.store.approve_work_item(self.user.id, self.work_item["id"], "plan")
        self.assertTrue(self.worker.run_once())
        patched = self.store.get_work_item(self.user.id, self.work_item["id"])
        self.assertEqual(patched["status"], "awaiting_publish_approval")
        self.assertEqual(patched["artifact"]["verification"]["mode"], "static")
        self.assertEqual(patched["artifact"]["patch"]["changed_files"], ["app/validation.py"])

        self.store.approve_work_item(self.user.id, self.work_item["id"], "publish")
        self.assertTrue(self.worker.run_once())
        completed = self.store.get_work_item(self.user.id, self.work_item["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["artifact"]["pr_number"], 17)
        self.assertEqual(completed["artifact"]["commit_sha"], "a" * 40)
        self.assertEqual(self.repositories.published[0]["changed"], "app/validation.py")
        self.assertEqual(self.github.pull_requests[0]["head"], completed["artifact"]["branch_name"])


if __name__ == "__main__":
    unittest.main()
