from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patchpilot.security import hash_password, normalize_email, verify_password  # noqa: E402


class SecurityTests(unittest.TestCase):
    def test_password_hash_is_salted_and_verifiable(self) -> None:
        first = hash_password("correct horse battery staple")
        second = hash_password("correct horse battery staple")

        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("correct horse battery staple", first))
        self.assertFalse(verify_password("wrong password", first))

    def test_email_is_normalized_and_validated(self) -> None:
        self.assertEqual(normalize_email("  Pilot@Example.COM "), "pilot@example.com")
        with self.assertRaises(ValueError):
            normalize_email("not-an-email")


if __name__ == "__main__":
    unittest.main()
