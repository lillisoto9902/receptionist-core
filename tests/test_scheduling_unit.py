"""Offline scheduling regression tests; no startup or database connections."""

import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app import main, companies
from company_fixture import configuration


class SchedulingFixture(unittest.TestCase):
    def setUp(self):
        marker = companies.context.set({'tenant_id': 'synthetic-a', 'configuration': configuration()})
        self.addCleanup(companies.context.reset, marker)
        previous = main.app.dependency_overrides.copy()
        main.app.dependency_overrides[companies.require_tenant] = lambda: companies.current()
        self.addCleanup(lambda: (main.app.dependency_overrides.clear(), main.app.dependency_overrides.update(previous)))
        self.now = datetime(2030, 1, 2, 6, tzinfo=timezone.utc)
        self.enterContext(patch.object(main, "get_business_now", return_value=self.now))
        self.enterContext(patch.object(main, "get_business_timezone", return_value=timezone.utc))
        self.network = self.enterContext(patch.object(
            main.psycopg2, "connect", side_effect=AssertionError("Database access forbidden")
        ))
        self.startup = self.enterContext(patch.object(
            main, "init_db", side_effect=AssertionError("Startup forbidden")
        ))
        self.conn = MagicMock()
        self.cursor = self.conn.cursor.return_value
        self.cursor.fetchall.return_value = []
        self.cursor.fetchone.return_value = (
            1, "Synthetic", "000", None, "consultation", "09:00", "form",
            "09:00", "scheduled", "consultation", "salon", 30, "low", self.now,
        )
        self.real_get_db_connection = main.get_db_connection
        self.db = self.enterContext(patch.object(main, "get_db_connection", return_value=self.conn))

    def tearDown(self):
        self.network.assert_not_called()
        self.startup.assert_not_called()

    def intake(self, preferred="09:00", reason="consultation"):
        return main.IntakeRequest(name="Synthetic", phone="000", reason=reason, preferred_time=preferred)

    def assert_no_write(self):
        self.conn.commit.assert_not_called()
        for call in self.cursor.execute.call_args_list:
            self.assertNotIn("INSERT", call.args[0].upper())


class BookingLookupTests(SchedulingFixture):
    def test_successful_empty_lookup_is_empty(self):
        self.assertEqual(main.get_active_bookings(), [])
        self.cursor.close.assert_called_once()
        self.conn.close.assert_called_once()
        self.assert_no_write()

    def test_connection_failure_is_not_empty(self):
        self.db.side_effect = RuntimeError("synthetic internal connection detail")
        with self.assertRaises(main.SchedulingDataError):
            main.get_active_bookings()
        self.assert_no_write()

    def test_query_failure_closes_resources(self):
        self.cursor.execute.side_effect = RuntimeError("synthetic query failure")
        with self.assertRaises(main.SchedulingDataError):
            main.get_active_bookings()
        self.cursor.close.assert_called_once()
        self.conn.close.assert_called_once()

    def test_fetch_failure_closes_resources(self):
        self.cursor.fetchall.side_effect = RuntimeError("synthetic fetch failure")
        with self.assertRaises(main.SchedulingDataError):
            main.get_active_bookings()
        self.cursor.close.assert_called_once()
        self.conn.close.assert_called_once()

    def test_cursor_creation_failure_closes_connection(self):
        self.conn.cursor.side_effect = RuntimeError("cursor failure")
        with self.assertRaises(main.SchedulingDataError):
            main.get_active_bookings()
        self.conn.close.assert_called_once()

    def test_malformed_booking_times_fail_whole_lookup(self):
        for value in (None, "", "string", "nonsense", "25:00", "09:60", "-1:00",
                      "09:00:garbage", "invalidT09:00", "2030-02-30T09:00"):
            with self.subTest(value=value):
                self.cursor.fetchall.return_value = [(self.now.replace(hour=10), 30), (value, 30)]
                with self.assertRaises(main.SchedulingDataError):
                    main.get_active_bookings()

    def test_invalid_stored_durations_fail_whole_lookup(self):
        for value in (None, 0, -1, "bad", "30", 30.5, True, float("inf")):
            with self.subTest(value=value):
                self.cursor.fetchall.return_value = [(self.now.replace(hour=9), value)]
                with self.assertRaises(main.SchedulingDataError):
                    main.get_active_bookings()

    def test_malformed_rows_fail_closed(self):
        for row in (None, (), ("09:00",), ("09:00", 30, "extra"), {0: "09:00", 1: 30}):
            with self.subTest(row=row):
                self.cursor.fetchall.return_value = [row]
                with self.assertRaises(main.SchedulingDataError):
                    main.get_active_bookings()

    def test_valid_rows_preserve_normalization_and_reserving_query(self):
        self.cursor.fetchall.return_value = [(self.now.replace(hour=10), 30), (self.now.replace(hour=9), 60)]
        self.assertEqual(main.get_active_bookings(), [(self.now.replace(hour=10), 30), (self.now.replace(hour=9), 60)])
        self.assertEqual(self.cursor.execute.call_args.args[0], """
            SELECT scheduled_at, duration_minutes
            FROM intake_requests
            WHERE tenant_id = %s
              AND (%s IS NULL OR id <> %s)
              AND appointment_status IN ('scheduled', 'pending', 'needs_confirmation', 'confirmed')
        """)

    def test_integrity_exception_propagates_through_all_evaluators(self):
        error = main.SchedulingDataError("synthetic internal detail")
        with patch.object(main, "get_active_bookings", side_effect=error):
            for evaluate in (
                lambda: main.is_slot_available("09:00", 30),
                lambda: main.find_next_available_slot(30),
                lambda: main.find_next_available_slot(30, "09:00"),
                lambda: main.find_available_options(30),
                lambda: main.find_available_options(30, "09:00"),
                lambda: main.create_intake(self.intake()),
            ):
                with self.subTest(evaluate=evaluate):
                    with self.assertRaises(main.SchedulingDataError) as caught:
                        evaluate()
                    self.assertIs(caught.exception, error)
        self.assert_no_write()

    def test_availability_failure_discards_earlier_options(self):
        for preferred in (None, "09:00"):
            with self.subTest(preferred=preferred):
                with patch.object(main, "get_active_bookings", side_effect=[[], main.SchedulingDataError()]):
                    with self.assertRaises(main.SchedulingDataError):
                        main.find_available_options(30, preferred)

    def test_lookup_failures_never_attempt_intake_insert(self):
        for failure in ("connection", "query", "fetch", "integrity"):
            with self.subTest(failure=failure):
                self.db.side_effect = RuntimeError() if failure == "connection" else None
                self.cursor.execute.side_effect = RuntimeError() if failure == "query" else None
                self.cursor.fetchall.side_effect = RuntimeError() if failure == "fetch" else None
                self.cursor.fetchall.return_value = [("bad", 30)] if failure == "integrity" else []
                with self.assertRaises(main.SchedulingDataError):
                    main.create_intake(self.intake())
                self.assert_no_write()

    def test_real_connection_wrapper_sanitizes_output(self):
        # Restore only the wrapper, keeping the driver itself mocked.
        self.network.side_effect = RuntimeError("synthetic secret SQL customer detail")
        output = io.StringIO()
        with patch.object(main, "get_db_connection", self.real_get_db_connection), \
                patch.dict(main.os.environ, {"DATABASE_URL": "synthetic-unused"}), redirect_stdout(output):
            with self.assertRaises(main.SchedulingDataError):
                main.get_active_bookings()
        self.assertEqual(output.getvalue(), "Database connection failed\n")
        self.network.assert_called_once()
        self.network.reset_mock()


class EligibilityTests(SchedulingFixture):
    def test_opening_and_before_opening(self):
        self.assertTrue(main.time_fits("09:00", 30))
        self.assertFalse(main.time_fits("08:30", 30))

    def test_grid(self):
        for value in ("09:00", "09:30", "10:00", "16:30"):
            self.assertTrue(main.time_fits(value, 30))
        for value in ("09:01", "09:15", "16:45"):
            self.assertFalse(main.time_fits(value, 30))

    def test_closing_boundary_depends_on_full_duration(self):
        for start, duration, fits in (("16:30", 30, True), ("16:00", 60, True),
                                     ("15:00", 120, True), ("16:30", 60, False),
                                     ("16:00", 90, False), ("17:00", 30, False)):
            with self.subTest(start=start, duration=duration):
                self.assertEqual(main.time_fits(start, duration), fits)

    def test_interval_adjacency_is_not_overlap(self):
        self.assertFalse(main.times_overlap("09:00", 30, "09:30", 30))
        self.assertFalse(main.times_overlap("09:30", 30, "09:00", 30))

    def test_conflicts_remain_unavailable(self):
        self.cursor.fetchall.return_value = [(self.now.replace(hour=10), 60)]
        for start, duration in (("10:00", 30), ("09:30", 60), ("10:30", 60)):
            self.assertFalse(main.is_slot_available(start, duration))
        self.assertTrue(main.is_slot_available("09:30", 30))
        self.assertTrue(main.is_slot_available("11:00", 30))

    def test_hours_grid_shared_between_availability_and_intake(self):
        for reason, duration in (("consultation", 30), ("haircut", 60), ("color", 120)):
            for start in ("08:30", "09:00", "09:15", "15:00", "16:00", "16:30", "17:00"):
                with self.subTest(reason=reason, start=start):
                    self.cursor.execute.reset_mock()
                    self.conn.commit.reset_mock()
                    options = main.find_available_options(duration, start, limit=20)
                    offered = start in [item["time"] for item in options]
                    result = main.create_intake(self.intake(start, reason))
                    accepted = result["status"] == "scheduled"
                    self.assertEqual(offered, accepted)
                    self.assertEqual(accepted, main.time_fits(start, duration))
                    if accepted:
                        self.conn.commit.assert_called_once()
                    else:
                        self.assert_no_write()

    def test_lead_time_and_maximum_advance_preserved(self):
        self.assertIn("lead-time", main.get_booking_window_message("07:30"))
        self.assertIsNone(main.get_booking_window_message("08:00"))
        self.assertIn("maximum advance", main.get_booking_window_message((self.now + timedelta(days=31)).isoformat()))
        result = main.create_intake(self.intake((self.now + timedelta(days=31)).isoformat()))
        self.assertEqual(result["status"], "slot_unavailable")
        self.assertEqual(result["available_options"], [])
        self.assert_no_write()


if __name__ == "__main__":
    unittest.main()
