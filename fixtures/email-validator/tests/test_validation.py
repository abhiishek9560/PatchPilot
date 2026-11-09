import unittest

from app.validation import is_valid_email


class EmailValidationTests(unittest.TestCase):
    def test_accepts_complete_address(self) -> None:
        self.assertTrue(is_valid_email("user@example.com"))

    def test_rejects_domain_without_dot(self) -> None:
        self.assertFalse(is_valid_email("user@example"))

    def test_rejects_missing_local_part(self) -> None:
        self.assertFalse(is_valid_email("@example.com"))


if __name__ == "__main__":
    unittest.main()
