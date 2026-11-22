from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patchpilot.github import process_webhook_event  # noqa: E402
from patchpilot.models import AgentRun, Issue  # noqa: E402
from patchpilot.product_store import PostgresProductStore  # noqa: E402
from patchpilot.security import hash_password  # noqa: E402
from patchpilot.store import PostgresRunStore  # noqa: E402


def _schema_url(database_url: str, schema: str) -> str:
    parts = urlsplit(database_url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("options", f"-csearch_path={schema}"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@unittest.skipUnless(
    os.getenv("PATCHPILOT_TEST_DATABASE_URL"),
    "PATCHPILOT_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)
class PostgresStoreIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import psycopg
        from psycopg import sql

        cls.base_url = os.environ["PATCHPILOT_TEST_DATABASE_URL"]
        cls.schema = f"patchpilot_test_{uuid4().hex}"
        with psycopg.connect(cls.base_url, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
        cls.database_url = _schema_url(cls.base_url, cls.schema)

    @classmethod
    def tearDownClass(cls) -> None:
        import psycopg
        from psycopg import sql

        with psycopg.connect(cls.base_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema))
            )

    def test_product_and_run_stores_complete_core_workflow(self) -> None:
        product_store = PostgresProductStore(self.database_url)
        run_store = PostgresRunStore(self.database_url)
        unique = uuid4().hex
        user, organization = product_store.register_user(
            f"postgres-{unique}@example.com",
            "PostgreSQL Pilot",
            hash_password("a secure integration-test password"),
        )

        token = product_store.create_session(user.id, 1)
        self.assertEqual(product_store.user_for_session(token), user)

        state = product_store.begin_github_setup(user.id, organization.id)
        installation_id = 8_000_000_000 + int(unique[:6], 16)
        repository_id = 9_000_000_000 + int(unique[6:12], 16)
        installation = {
            "id": installation_id,
            "account": {"login": "patchpilot-integration", "type": "Organization"},
            "repository_selection": "selected",
        }
        repository = {
            "id": repository_id,
            "full_name": f"patchpilot-integration/repository-{unique[:8]}",
            "default_branch": "main",
            "private": True,
        }
        issue = {
            "number": 42,
            "title": "PostgreSQL deployment smoke issue",
            "body": "Exercise the production persistence adapter.",
            "state": "open",
            "html_url": "https://example.com/issues/42",
            "user": {"login": "integration-test"},
            "labels": [{"name": "bug"}],
        }
        process_webhook_event(
            product_store,
            "installation",
            {"action": "created", "installation": installation, "repositories": [repository]},
        )
        product_store.claim_github_installation(state, installation_id, user.id)
        process_webhook_event(
            product_store,
            "issues",
            {
                "action": "opened",
                "installation": installation,
                "repository": repository,
                "issue": issue,
            },
        )

        self.assertTrue(product_store.record_webhook_delivery(unique, "issues"))
        self.assertFalse(product_store.record_webhook_delivery(unique, "issues"))
        self.assertEqual(product_store.list_issues(user.id)[0]["labels"], ["bug"])

        work_item = product_store.assign_issue(user.id, repository_id, issue["number"])
        planning_job = product_store.claim_job("postgres-planner")
        self.assertIsNotNone(planning_job)
        self.assertEqual(planning_job["kind"], "create_plan")
        product_store.complete_job(planning_job["id"], "postgres-planner")
        product_store.record_plan(
            work_item["id"],
            {"summary": "Verify PostgreSQL", "steps": ["Run the production adapter tests"]},
        )
        product_store.approve_work_item(user.id, work_item["id"], "plan")
        patch_job = product_store.claim_job("postgres-patcher")
        self.assertIsNotNone(patch_job)
        self.assertEqual(patch_job["kind"], "create_patch")
        product_store.record_patch_result(
            work_item["id"],
            branch_name=f"patchpilot/issue-42-{unique[:8]}",
            patch={
                "unified_diff": "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n",
                "rationale": "PostgreSQL artifact test",
                "changed_files": ["app.py"],
            },
            verification={"mode": "static", "passed": True},
        )
        product_store.complete_job(patch_job["id"], "postgres-patcher")
        product_store.approve_work_item(user.id, work_item["id"], "publish")
        publish_job = product_store.claim_job("postgres-publisher")
        self.assertIsNotNone(publish_job)
        self.assertEqual(publish_job["kind"], "publish_draft_pr")
        product_store.record_pull_request(
            work_item["id"],
            commit_sha="a" * 40,
            pr_url="https://github.com/patchpilot-integration/repository/pull/1",
            pr_number=1,
        )
        product_store.complete_job(publish_job["id"], "postgres-publisher")
        completed = product_store.get_work_item(user.id, work_item["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["artifact"]["pr_number"], 1)

        run = AgentRun(
            issue=Issue(repository=repository["full_name"], number=42, title=issue["title"], body=""),
            workspace="/tmp/patchpilot-postgres-test",
        )
        run_store.save(run)
        self.assertEqual(run_store.get(run.id).issue.repository, repository["full_name"])
        self.assertEqual(run_store.list()[0].id, run.id)


if __name__ == "__main__":
    unittest.main()
