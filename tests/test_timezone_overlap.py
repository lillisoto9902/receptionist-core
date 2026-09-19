"""Absolute interval boundaries, independent of local-date representation."""
from datetime import datetime, timezone
from unittest.mock import patch
from app import main, companies
import unittest
from company_fixture import configuration


class TimezoneOverlapTests(unittest.TestCase):
    def setUp(self):
        marker = companies.context.set({'tenant_id':'synthetic-a','configuration':configuration(timezone='UTC')})
        self.addCleanup(companies.context.reset, marker)
        companies.current()['configuration'].update(timezone='America/New_York', opening='00:00', closing='23:30')

    def available(self, existing, duration, requested, requested_duration):
        with patch.object(main, 'get_active_bookings', return_value=[(datetime.fromisoformat(existing).astimezone(timezone.utc), duration)]):
            return main.is_slot_available(main.parse_requested_datetime(requested).strftime('%H:%M'), requested_duration, requested)

    def test_cross_midnight_overlap(self):
        self.assertFalse(self.available('2030-01-03T04:30:00+00:00',60,'2030-01-03T00:00:00-05:00',60))

    def test_cross_midnight_separate_intervals(self):
        self.assertTrue(self.available('2030-01-02T23:00:00-05:00',30,'2030-01-03T00:30:00-05:00',30))

    def test_adjacent_interval_is_free(self):
        self.assertTrue(self.available('2030-01-03T04:30:00+00:00',60,'2030-01-03T00:30:00-05:00',60))

    def test_same_instant_different_offset_conflicts(self):
        self.assertFalse(self.available('2030-01-03T14:00:00+00:00',60,'2030-01-03T09:00:00-05:00',60))

    def test_adjacent_dates_are_independent(self):
        self.assertTrue(self.available('2030-01-03T14:00:00+00:00',60,'2030-01-04T09:00:00-05:00',60))

    def test_explicit_repeated_hour_offset_preserved(self):
        self.assertFalse(self.available('2030-11-03T06:30:00+00:00',30,'2030-11-03T01:30:00-05:00',30))
