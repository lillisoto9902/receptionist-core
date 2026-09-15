"""Run with: python -m unittest discover -s tests -v

Uses generated synthetic credentials; never loads .env or starts the application.
"""

import io
import logging
import secrets
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from fastapi import HTTPException

from app import main


class AdminAuthTests(unittest.TestCase):
    def setUp(self):
        self.configured = secrets.token_hex(32)
        self.incorrect = secrets.token_hex(33)
        self.enterContext(
            patch.dict(main.os.environ, {"ADMIN_API_TOKEN": self.configured}, clear=True)
        )
        self.output = io.StringIO()
        self.enterContext(redirect_stdout(self.output))
        self.enterContext(redirect_stderr(self.output))
        handler = logging.StreamHandler(self.output)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)

    def assert_rejected(self, header, status=401):
        with self.assertRaises(HTTPException) as caught:
            main.require_admin_auth(header)
        error = caught.exception
        # Boolean assertions avoid including credential-bearing values on failure.
        self.assertTrue(error.status_code == status, "Unexpected error status")
        expected_detail = "Unauthorized" if status == 401 else "Internal server error"
        self.assertTrue(error.detail == expected_detail, "Error detail is not generic")
        expected_headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        self.assertTrue(error.headers == expected_headers, "Unexpected challenge")
        response = str(error) + repr(error.detail) + repr(error.headers)
        submitted = header.partition(" ")[2].strip() if header else None
        for credential in (self.configured, self.incorrect, submitted):
            if credential:
                self.assertFalse(credential in response, "Credential disclosed in error")
        self.assertTrue(self.output.getvalue() == "", "Authentication emitted output")

    def test_missing_authorization(self):
        self.assert_rejected(None)

    def test_missing_bearer_prefix(self):
        self.assert_rejected("Basic " + self.incorrect)

    def test_malformed_bearer_header(self):
        self.assert_rejected("Bearer")

    def test_empty_bearer_credential(self):
        self.assert_rejected("Bearer ")

    def test_incorrect_ascii(self):
        self.assert_rejected("Bearer " + self.incorrect)

    def test_incorrect_non_ascii(self):
        self.assert_rejected("Bearer " + chr(0xE9))

    def test_mixed_unicode(self):
        self.assert_rejected("Bearer " + self.incorrect + chr(0x1F512))

    def test_unpaired_surrogate(self):
        self.assert_rejected("Bearer " + chr(0xD800))

    def test_correct_credential(self):
        self.assertTrue(main.require_admin_auth("Bearer " + self.configured) is True)
        self.assertTrue(self.output.getvalue() == "", "Authentication emitted output")

    def test_missing_server_configuration(self):
        del main.os.environ["ADMIN_API_TOKEN"]
        self.assert_rejected("Bearer " + self.incorrect, status=500)

    def test_empty_server_configuration(self):
        main.os.environ["ADMIN_API_TOKEN"] = ""
        self.assert_rejected("Bearer " + self.incorrect, status=500)

    def test_non_ascii_server_configuration_fails_closed(self):
        main.os.environ["ADMIN_API_TOKEN"] = self.configured + chr(0xE9)
        self.assert_rejected("Bearer " + self.configured)

    def test_constant_time_comparison_used(self):
        with patch.object(main.secrets, "compare_digest", wraps=secrets.compare_digest) as compare:
            self.assertTrue(main.require_admin_auth("Bearer " + self.configured) is True)
            self.assertTrue(compare.call_count == 1, "Constant-time comparison not used")
        self.assertTrue(self.output.getvalue() == "", "Authentication emitted output")


if __name__ == "__main__":
    unittest.main()
