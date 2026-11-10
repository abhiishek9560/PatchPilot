from __future__ import annotations

import hashlib
import hmac
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patchpilot.github import GitHubAppClient, verify_webhook_signature  # noqa: E402


class GitHubWebhookTests(unittest.TestCase):
    def test_accepts_valid_signature(self) -> None:
        body = b'{"action":"opened"}'
        secret = "test-secret"
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook_signature(body, signature, secret))

    def test_rejects_invalid_signature(self) -> None:
        self.assertFalse(verify_webhook_signature(b"payload", "sha256=invalid", "secret"))
        self.assertFalse(verify_webhook_signature(b"payload", "invalid", "secret"))


class GitHubAppClientTests(unittest.TestCase):
    def test_app_jwt_has_short_lifetime_and_app_issuer(self) -> None:
        captured = {}

        def encode(payload: dict, private_key: str) -> str:
            captured.update(payload)
            self.assertEqual(private_key, "private-key")
            return "signed-app-jwt"

        client = GitHubAppClient("12345", "private-key", jwt_encoder=encode)

        self.assertEqual(client.app_jwt(now=1_000), "signed-app-jwt")
        self.assertEqual(captured, {"iat": 940, "exp": 1540, "iss": "12345"})

    def test_draft_pr_uses_repository_scoped_installation_token(self) -> None:
        calls = []

        def transport(method: str, url: str, headers: dict, payload: dict | None) -> dict:
            calls.append((method, url, headers, payload))
            if url.endswith("/access_tokens"):
                return {"token": "one-hour-token", "expires_at": "2026-11-10T20:00:00Z"}
            return {
                "html_url": "https://github.com/acme/api/pull/17",
                "number": 17,
                "title": "Fix #42",
            }

        client = GitHubAppClient(
            "12345",
            "private-key",
            transport=transport,
            jwt_encoder=lambda _payload, _key: "signed-app-jwt",
        )

        pull_request = client.create_draft_pull_request(
            installation_id=501,
            repository_id=901,
            repository="acme/api",
            title="Fix #42",
            head="patchpilot/issue-42",
            base="main",
            body="Verified by PatchPilot",
        )

        self.assertEqual(pull_request.number, 17)
        self.assertEqual(calls[0][2]["Authorization"], "Bearer signed-app-jwt")
        self.assertEqual(calls[0][3]["repository_ids"], [901])
        self.assertEqual(
            calls[0][3]["permissions"], {"contents": "write", "pull_requests": "write"}
        )
        self.assertEqual(calls[1][2]["Authorization"], "Bearer one-hour-token")
        self.assertTrue(calls[1][3]["draft"])


if __name__ == "__main__":
    unittest.main()
