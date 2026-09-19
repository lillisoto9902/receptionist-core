"""Focused date and precision checks without database access."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from app import main, companies
from company_fixture import configuration


class AppointmentDateTests(unittest.TestCase):
    def setUp(self):
        marker = companies.context.set({'tenant_id':'synthetic-a','configuration':configuration(timezone='UTC')})
        self.addCleanup(companies.context.reset,marker)
        self.enterContext(patch.object(main,'get_business_now',return_value=datetime(2030,1,2,6,tzinfo=timezone.utc)))

    def test_datetime_date_preserved(self):
        self.assertEqual(main.parse_requested_datetime('2030-01-03T13:00:00+00:00').isoformat(),'2030-01-03T13:00:00+00:00')

    def test_offset_converted_to_company_timezone(self):
        self.assertEqual(main.parse_requested_datetime('2030-01-03T13:00:00+02:00').isoformat(),'2030-01-03T11:00:00+00:00')

    def test_invalid_dates_do_not_fall_back_to_clock_time(self):
        for value in ('invalidT09:00','2030-02-30T09:00','09:00:garbage'):
            self.assertFalse(main.is_valid_preferred_time(value))

    def test_subminute_values_rejected_not_truncated(self):
        for value in ('09:00:30','2030-01-03T09:00:01Z','2030-01-03T09:00:00.001Z'):
            self.assertFalse(main.is_valid_preferred_time(value))

    def test_time_only_resolves_explicit_current_date(self):
        self.assertEqual(main.parse_requested_datetime('09:00').isoformat(),'2030-01-02T09:00:00+00:00')

    def test_nonexistent_local_time_rejected(self):
        companies.current()['configuration']['timezone']='America/New_York'
        self.assertIsNone(main.parse_requested_datetime('2030-03-10T02:30:00'))
