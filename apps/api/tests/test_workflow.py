from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "apps" / "api"))

from patchpilot.github import DemoPublisher  # noqa: E402
from patchpilot.models import Issue, RunStatus  # noqa: E402
from patchpilot.planner import DeterministicPlanner  # noqa: E402
from patchpilot.store import MemoryRunStore  # noqa: E402
from patchpilot.workflow import InvalidTransition, PatchPilotWorkflow  # noqa: E402


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name) / "repo"
        shutil.copytree(PROJECT_ROOT / "fixtures" / "email-validator", self.workspace)
        self.store = MemoryRunStore()
        self.workflow = PatchPilotWorkflow(
            self.store, DeterministicPlanner(), DemoPublisher()
        )
        self.run = self.workflow.create_run(
            Issue("acme/accounts-api", 142, "Broken validation", "Reject incomplete domains"),
            self.workspace,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_complete_run_requires_two_approvals(self) -> None:
        run = self.workflow.run_until_pause(self.run.id)
        self.assertEqual(run.status, RunStatus.AWAITING_PLAN_APPROVAL)
        self.assertIsNotNone(run.reproduction)
        self.assertFalse(run.reproduction.passed)

        self.workflow.approve(run.id, "plan", "reviewer@example.com")
        run = self.workflow.run_until_pause(run.id)
        self.assertEqual(
            run.status,
            RunStatus.AWAITING_PUBLISH_APPROVAL,
            msg=run.failure,
        )
        self.assertTrue(all(result.passed for result in run.verification))
        self.assertIsNone(run.pr_url)

        run = self.workflow.approve(run.id, "publish", "reviewer@example.com")
        self.assertEqual(run.status, RunStatus.COMPLETED)
        self.assertIn("github.com", run.pr_url)

    def test_publish_cannot_skip_plan_approval(self) -> None:
        run = self.workflow.run_until_pause(self.run.id)
        with self.assertRaises(InvalidTransition):
            self.workflow.approve(run.id, "publish", "reviewer@example.com")

    def test_rejection_is_terminal(self) -> None:
        run = self.workflow.run_until_pause(self.run.id)
        run = self.workflow.reject(run.id, "reviewer@example.com", "Needs a smaller scope")
        self.assertEqual(run.status, RunStatus.REJECTED)
        self.assertEqual(self.workflow.run_until_pause(run.id).status, RunStatus.REJECTED)

    def test_unreproducible_issue_fails_without_writing(self) -> None:
        validator = self.workspace / "app" / "validation.py"
        validator.write_text(
            'def is_valid_email(value: str) -> bool:\n'
            '    local, separator, domain = value.partition("@")\n'
            '    return bool(local and separator and "." in domain)\n',
            encoding="utf-8",
        )
        run = self.workflow.run_until_pause(self.run.id)
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertIn("could not be reproduced", run.failure.lower())
        self.assertIsNone(run.patch)


if __name__ == "__main__":
    unittest.main()
