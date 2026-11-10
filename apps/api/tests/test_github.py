from __future__ import annotations

import hashlib
import hmac
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patchpilot.github import verify_webhook_signature  # noqa: E402


class GitHubWebhookTests(unittest.TestCase):
    def test_accepts_valid_signature(self) -> None:
        body = b'{"action":"opened"}'
        secret = "test-secret"
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook_signature(body, signature, secret))

    def test_rejects_invalid_signature(self) -> None:
        self.assertFalse(verify_webhook_signature(b"payload", "sha256=invalid", "secret"))
        self.assertFalse(verify_webhook_signature(b"payload", "invalid", "secret"))


if __name__ == "__main__":
    unittest.main()
