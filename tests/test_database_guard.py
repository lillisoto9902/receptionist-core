"""Offline guard regression tests; all credentials, connections and OS facts mocked."""

import io
import ipaddress
import traceback
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

from integration import _database_guard as guard


class DatabaseGuardTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(guard.os.environ, {"RUN_RECEPTIONIST_DB_INTEGRATION": "1"}, clear=True))
        self.secret = "synthetic-password-not-a-real-credential"
        self.urls = {
            role: f"postgresql://{role}:{self.secret}@127.0.0.1:55432/{guard.DATABASE}"
            for role in (guard.APP_ROLE, guard.MIGRATOR_ROLE)
        }
        self.config = "\n".join((
            "RECEPTIONIST_TEST_DATABASE_HOST=127.0.0.1",
            "RECEPTIONIST_TEST_DATABASE_PORT=55432",
            "RECEPTIONIST_TEST_DATABASE_NAME=" + guard.DATABASE,
            "RECEPTIONIST_TEST_DATABASE_URL=" + self.urls[guard.APP_ROLE],
            "RECEPTIONIST_TEST_MIGRATOR_DATABASE_URL=" + self.urls[guard.MIGRATOR_ROLE],
        ))
        # Intercept every Path read/existence check; no real secrets or PID files.
        self.read = self.enterContext(patch.object(guard.Path, "read_text", autospec=True, side_effect=self.read_file))
        self.enterContext(patch.object(guard.Path, "exists", return_value=False))
        self.connection = MagicMock()
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.driver = self.enterContext(patch.object(guard.psycopg2, "connect", return_value=self.connection))
        self.os_state = {
            "listeners": [{"LocalAddress": "127.0.0.1", "LocalPort": 55432, "OwningProcess": 100}],
            "backend": {
                "ParentProcessId": 100,
                "ExecutablePath": r"C:\Program Files\PostgreSQL\18\bin\postgres.exe",
            },
        }
        self.windows = self.enterContext(patch.object(guard, "windows_state", return_value=self.os_state))
        self.process = self.enterContext(patch.object(guard.subprocess, "run", side_effect=AssertionError("OS process inspection forbidden")))
        self.output = io.StringIO()
        self.enterContext(redirect_stdout(self.output))
        self.enterContext(redirect_stderr(self.output))
        self.identity()

    def read_file(self, path, *args, **kwargs):
        if path == guard.ROOT / "secrets" / "database.env":
            return self.config
        if path == guard.DATA / "postmaster.pid":
            return f"100\n{guard.DATA}\n0\n55432\n\n127.0.0.1\n\nready\n"
        if path == guard.DATA / "PG_VERSION":
            return "18\n"
        raise AssertionError("Unexpected file read")

    def identity(self, role=guard.APP_ROLE, address="127.0.0.1", port=55432, database=guard.DATABASE, version="180004"):
        self.cursor.fetchall.return_value = [(version, database, role, address, port, 101)]

    def tearDown(self):
        self.process.assert_not_called()
        self.assertEqual(self.output.getvalue(), "")

    def assert_failure(self, action, stage):
        with self.assertRaises(guard.SafetyError) as caught:
            action()
        self.assertEqual(str(caught.exception), stage + " failed")
        rendered = "".join(traceback.format_exception(caught.exception))
        for sensitive in (self.secret, *self.urls.values(), "SCRAM-SHA-256$synthetic"):
            self.assertNotIn(sensitive, rendered)

    def test_connection_kwargs_are_explicit_and_service_is_absent(self):
        target = guard.Target()
        for role in (guard.APP_ROLE, guard.MIGRATOR_ROLE):
            with self.subTest(role=role):
                self.identity(role)
                self.assertIs(target.connect(role), self.connection)
                args, kwargs = self.driver.call_args
                self.assertEqual(args, ())
                self.assertNotIn("service", kwargs)
                self.assertEqual(kwargs["host"], "127.0.0.1")
                self.assertEqual(kwargs["hostaddr"], "127.0.0.1")
                self.assertEqual(kwargs["port"], 55432)
                self.assertEqual(kwargs["dbname"], guard.DATABASE)
                self.assertEqual(kwargs["user"], role)
                self.assertEqual(kwargs["connect_timeout"], 5)
                self.assertFalse(self.connection.autocommit)

    def test_sql_projects_host_without_inet_mask(self):
        # Model PostgreSQL's host() result for the diagnosed /32 representation.
        self.identity(address=str(ipaddress.ip_interface("127.0.0.1/32").ip))
        guard.Target().connect(guard.APP_ROLE)
        statement = self.cursor.execute.call_args.args[0]
        self.assertIn("host(inet_server_addr())", statement)
        self.assertNotIn("inet_server_addr()::text", statement)

    def test_unapproved_sql_addresses_are_rejected(self):
        target = guard.Target()
        for address in ("0.0.0.0", "127.0.0.2", "::1", "::", "192.0.2.1", "localhost", None):
            with self.subTest(address=address):
                self.identity(address=address)
                self.assert_failure(lambda: target.connect(guard.APP_ROLE), "SQL server-identity validation")
        self.windows.assert_not_called()

    def test_other_sql_identity_mismatches_are_rejected(self):
        target = guard.Target()
        for change in ({"role": guard.MIGRATOR_ROLE}, {"port": 5432}, {"database": "postgres"}, {"version": "180003"}):
            with self.subTest(change=change):
                self.identity(**change)
                self.assert_failure(lambda: target.connect(guard.APP_ROLE), "SQL server-identity validation")

    def test_credential_loading_failure_has_its_own_stage(self):
        self.read.side_effect = OSError(self.urls[guard.APP_ROLE])
        self.assert_failure(guard.Target, "Credential/configuration loading")
        self.driver.assert_not_called()

    def test_duplicate_configuration_is_rejected_before_connect(self):
        self.config += "\nRECEPTIONIST_TEST_DATABASE_HOST=127.0.0.1"
        self.assert_failure(guard.Target, "Credential/configuration loading")
        self.driver.assert_not_called()

    def test_url_target_failures_have_their_own_stage(self):
        original = self.config
        for old, replacement in ((":55432/", ":5432/"), ("@127.0.0.1:", "@remote.invalid:"),
                                 ("@127.0.0.1:", "@localhost:"), ("/receptionist_core_test", "/postgres"),
                                 (guard.APP_ROLE + ":", "unexpected_role:")):
            with self.subTest(replacement=replacement):
                self.config = original.replace(old, replacement)
                self.assert_failure(guard.Target, "URL/target validation")
        self.driver.assert_not_called()

    def test_malformed_url_does_not_expose_its_value(self):
        self.config = self.config.replace(":55432/", ":invalid-port/")
        self.assert_failure(guard.Target, "URL/target validation")
        self.driver.assert_not_called()

    def test_inherited_postgresql_environment_is_rejected_without_mutation(self):
        target = guard.Target()
        for key in ("PGSERVICE", "PGSERVICEFILE", "PGHOST", "PGPORT", "PGPASSWORD", "PGOPTIONS"):
            with self.subTest(key=key), patch.dict(guard.os.environ, {key: "synthetic-override"}):
                before = dict(guard.os.environ)
                self.assert_failure(lambda: target.connect(guard.APP_ROLE), "URL/target validation")
                self.assertEqual(dict(guard.os.environ), before)
        self.driver.assert_not_called()

    def test_connection_failure_is_sanitized_and_separate_from_identity(self):
        target = guard.Target()
        self.driver.side_effect = guard.psycopg2.OperationalError(self.urls[guard.APP_ROLE])
        self.assert_failure(lambda: target.connect(guard.APP_ROLE), "Connection/authentication")
        self.cursor.execute.assert_not_called()
        self.windows.assert_not_called()

    def test_sql_failure_is_sanitized_and_closes_connection(self):
        target = guard.Target()
        self.cursor.execute.side_effect = guard.psycopg2.Error(self.urls[guard.APP_ROLE])
        self.assert_failure(lambda: target.connect(guard.APP_ROLE), "SQL server-identity validation")
        self.connection.close.assert_called_once()
        self.windows.assert_not_called()

    def test_process_failure_has_its_own_sanitized_stage(self):
        target = guard.Target()
        self.windows.side_effect = RuntimeError(self.urls[guard.APP_ROLE])
        self.assert_failure(lambda: target.connect(guard.APP_ROLE), "Process/PID/listener validation")
        self.connection.close.assert_called_once()

    def test_listener_mismatch_still_fails_closed(self):
        target = guard.Target()
        self.os_state["listeners"][0]["OwningProcess"] = 999
        self.assert_failure(lambda: target.connect(guard.APP_ROLE), "Process/PID/listener validation")

    def test_close_failure_cannot_disclose_connection_details(self):
        target = guard.Target()
        self.identity(address="192.0.2.1")
        self.connection.close.side_effect = RuntimeError(self.urls[guard.APP_ROLE])
        self.assert_failure(lambda: target.connect(guard.APP_ROLE), "SQL server-identity validation")

    def test_sensitive_sql_settings_not_required(self):
        guard.Target().connect(guard.APP_ROLE)
        statement = self.cursor.execute.call_args.args[0].lower()
        for setting in ("data_directory", "config_file", "hba_file"):
            self.assertNotIn(setting, statement)

    def test_no_opt_in_reads_no_configuration_and_connects_nowhere(self):
        del guard.os.environ["RUN_RECEPTIONIST_DB_INTEGRATION"]
        self.assert_failure(guard.Target, "Credential/configuration loading")
        self.read.assert_not_called()
        self.driver.assert_not_called()


if __name__ == "__main__":
    unittest.main()
