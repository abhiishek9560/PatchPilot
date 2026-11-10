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
            {"action": "opened", "installation": installation, "repository": repository, "issue": issue},
        )

        repositories = self.store.list_repositories(self.user.id)
        issues = self.store.list_issues(self.user.id)
        self.assertEqual(repositories[0]["full_name"], "patchpilot-labs/sample-api")
        self.assertEqual(issues[0]["number"], 42)
        self.assertEqual(issues[0]["labels"], ["bug"])

    def test_webhook_delivery_is_idempotent(self) -> None:
        self.assertTrue(self.store.record_webhook_delivery("delivery-1", "issues"))
        self.assertFalse(self.store.record_webhook_delivery("delivery-1", "issues"))


if __name__ == "__main__":
    unittest.main()
