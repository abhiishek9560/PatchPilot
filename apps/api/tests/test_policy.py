from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patchpilot.policy import ExecutionPolicy, PolicyViolation  # noqa: E402


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.policy = ExecutionPolicy(
            workspace_root=self.root,
            allowed_commands=("python3", "git"),
            protected_paths=(".git", ".github/workflows", ".env", "infra"),
            max_changed_files=2,
            max_patch_bytes=2_000,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_rejects_shell_metacharacters(self) -> None:
        with self.assertRaises(PolicyViolation):
            self.policy.validate_command(["python3", "-c", "print(1); rm -rf x"])

    def test_rejects_workspace_escape(self) -> None:
        with self.assertRaises(PolicyViolation):
            self.policy.resolve_path("../outside.txt")

    def test_rejects_protected_patch(self) -> None:
        diff = "--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-A=1\n+A=2\n"
        with self.assertRaises(PolicyViolation):
            self.policy.validate_patch(diff)

    def test_accepts_bounded_patch(self) -> None:
        diff = "--- a/app/main.py\n+++ b/app/main.py\n@@ -1 +1 @@\n-old\n+new\n"
        self.assertEqual(self.policy.validate_patch(diff), ["app/main.py"])


if __name__ == "__main__":
    unittest.main()
