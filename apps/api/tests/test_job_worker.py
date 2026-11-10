from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patchpilot.github import process_webhook_event  # noqa: E402
from patchpilot.job_worker import DurableJobWorker  # noqa: E402
from patchpilot.product_store import SQLiteProductStore  # noqa: E402
from patchpilot.security import hash_password  # noqa: E402


class DurableJobWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = SQLiteProductStore(Path(self.temporary.name) / "worker.db")
        self.user, organization = self.store.register_user(
            "worker@example.com", "Worker Test", hash_password("a secure password")
        )
        state = self.store.begin_github_setup(self.user.id, organization.id)
        installation = {
            "id": 7,
            "account": {"login": "acme", "type": "Organization"},
            "repository_selection": "selected",
        }
        repository = {"id": 8, "full_name": "acme/api", "default_branch": "main"}
        issue = {
            "number": 9,
            "title": "Fix bug",
            "body": "broken",
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

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_dispatches_and_completes_claimed_job(self) -> None:
        handled = []
        worker = DurableJobWorker(
            self.store,
            "worker-1",
            {"create_plan": lambda job: handled.append(job["work_item_id"])},
        )

        self.assertTrue(worker.run_once())
        self.assertEqual(handled, [self.work_item["id"]])
        self.assertFalse(worker.run_once())

    def test_handler_failure_is_retried_then_marks_work_failed(self) -> None:
        worker = DurableJobWorker(
            self.store,
            "worker-1",
            {"create_plan": lambda _job: (_ for _ in ()).throw(RuntimeError("boom"))},
            retry_delay_seconds=0,
        )

        self.assertTrue(worker.run_once())
        self.assertTrue(worker.run_once())
        self.assertTrue(worker.run_once())

        current = self.store.get_work_item(self.user.id, self.work_item["id"])
        self.assertEqual(current["status"], "failed")
        self.assertFalse(worker.run_once())


if __name__ == "__main__":
    unittest.main()
