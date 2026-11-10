from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patchpilot.github import process_webhook_event  # noqa: E402
from patchpilot.product_store import SQLiteProductStore  # noqa: E402
from patchpilot.security import hash_password  # noqa: E402


class ProductStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = SQLiteProductStore(Path(self.temporary.name) / "product.db")
        self.user, self.organization = self.store.register_user(
            "pilot@example.com", "Patch Pilot", hash_password("a secure password")
        )

    def connect_issue_fixture(self) -> tuple[dict, dict, dict]:
        state = self.store.begin_github_setup(self.user.id, self.organization.id)
        installation = {
            "id": 501,
            "account": {"login": "patchpilot-labs", "type": "Organization"},
            "repository_selection": "selected",
        }
        repository = {
            "id": 901,
            "full_name": "patchpilot-labs/sample-api",
            "default_branch": "main",
            "private": True,
        }
        issue = {
            "number": 42,
            "title": "Validator accepts bad email",
            "body": "Please fix it",
            "state": "open",
            "html_url": "https://github.com/patchpilot-labs/sample-api/issues/42",
            "user": {"login": "octocat"},
            "labels": [{"name": "bug"}],
        }
        process_webhook_event(
            self.store,
            "installation",
            {"action": "created", "installation": installation, "repositories": [repository]},
        )
        self.store.claim_github_installation(state, 501, self.user.id)
        process_webhook_event(
            self.store,
            "issues",
            {
                "action": "opened",
                "installation": installation,
                "repository": repository,
                "issue": issue,
            },
        )
        return installation, repository, issue

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_registration_session_and_membership(self) -> None:
        token = self.store.create_session(self.user.id, 14)

        self.assertEqual(self.store.user_for_session(token), self.user)
        self.assertEqual(self.store.organizations_for_user(self.user.id)[0].role, "owner")

        self.store.delete_session(token)
        self.assertIsNone(self.store.user_for_session(token))

    def test_duplicate_email_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.store.register_user(
                "pilot@example.com", "Another Pilot", hash_password("another password")
            )

    def test_signed_webhook_projection_can_be_claimed_and_queried(self) -> None:
        self.connect_issue_fixture()

        repositories = self.store.list_repositories(self.user.id)
        issues = self.store.list_issues(self.user.id)
        self.assertEqual(repositories[0]["full_name"], "patchpilot-labs/sample-api")
        self.assertEqual(issues[0]["number"], 42)
        self.assertEqual(issues[0]["labels"], ["bug"])

    def test_webhook_delivery_is_idempotent(self) -> None:
        self.assertTrue(self.store.record_webhook_delivery("delivery-1", "issues"))
        self.assertFalse(self.store.record_webhook_delivery("delivery-1", "issues"))

    def test_issue_assignment_is_idempotent_and_creates_leased_job(self) -> None:
        self.connect_issue_fixture()

        first = self.store.assign_issue(self.user.id, 901, 42)
        second = self.store.assign_issue(self.user.id, 901, 42)
        job = self.store.claim_job("worker-1")

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["status"], "queued_for_plan")
        self.assertIsNotNone(job)
        self.assertEqual(job["work_item_id"], first["id"])
        self.assertEqual(job["kind"], "create_plan")
        self.assertEqual(job["attempts"], 1)
        with self.assertRaises(PermissionError):
            self.store.complete_job(job["id"], "worker-2")
        self.store.complete_job(job["id"], "worker-1")

    def test_plan_feedback_versions_and_requeues_work(self) -> None:
        self.connect_issue_fixture()
        work_item = self.store.assign_issue(self.user.id, 901, 42)
        initial_job = self.store.claim_job("worker-1")
        self.store.complete_job(initial_job["id"], "worker-1")
        plan = {"summary": "Tighten email validation", "steps": ["Add regression test"]}

        recorded = self.store.record_plan(work_item["id"], plan)
        feedback = self.store.submit_plan_feedback(
            self.user.id, work_item["id"], "Also cover uppercase domains."
        )
        revision_job = self.store.claim_job("worker-2")

        self.assertEqual(recorded["plan_version"], 1)
        self.assertEqual(feedback["message"], "Also cover uppercase domains.")
        self.assertEqual(revision_job["kind"], "revise_plan")
        self.assertEqual(revision_job["payload"]["plan_version"], 1)
        current = self.store.get_work_item(self.user.id, work_item["id"])
        self.assertEqual(current["status"], "queued_for_plan_revision")
        self.assertEqual(current["feedback"][0]["plan_version"], 1)

    def test_plan_approval_queues_patch_exactly_once(self) -> None:
        self.connect_issue_fixture()
        work_item = self.store.assign_issue(self.user.id, 901, 42)
        planning_job = self.store.claim_job("planner")
        self.store.complete_job(planning_job["id"], "planner")
        self.store.record_plan(work_item["id"], {"summary": "Fix it", "steps": []})

        approval = self.store.approve_work_item(self.user.id, work_item["id"], "plan")
        patch_job = self.store.claim_job("patcher")

        self.assertEqual(approval["stage"], "plan")
        self.assertEqual(patch_job["kind"], "create_patch")
        self.assertEqual(
            self.store.get_work_item(self.user.id, work_item["id"])["status"],
            "queued_for_patch",
        )
        with self.assertRaisesRegex(ValueError, "Cannot approve"):
            self.store.approve_work_item(self.user.id, work_item["id"], "plan")

    def test_other_user_cannot_assign_or_read_workspace_issue(self) -> None:
        self.connect_issue_fixture()
        stranger, _ = self.store.register_user(
            "stranger@example.com", "Stranger", hash_password("another secure password")
        )
        work_item = self.store.assign_issue(self.user.id, 901, 42)

        with self.assertRaises(PermissionError):
            self.store.assign_issue(stranger.id, 901, 42)
        with self.assertRaises(KeyError):
            self.store.get_work_item(stranger.id, work_item["id"])

    def test_automatic_assignment_prefers_available_bug(self) -> None:
        self.connect_issue_fixture()

        work_item = self.store.auto_assign_next_issue(self.user.id, self.organization.id)

        self.assertEqual(work_item["repository_id"], 901)
        self.assertEqual(work_item["issue_number"], 42)
        self.assertEqual(work_item["selection_mode"], "automatic")
        with self.assertRaisesRegex(LookupError, "No unassigned"):
            self.store.auto_assign_next_issue(self.user.id, self.organization.id)


if __name__ == "__main__":
    unittest.main()
