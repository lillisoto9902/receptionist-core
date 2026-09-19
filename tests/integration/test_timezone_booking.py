"""Real authenticated booking intervals survive company timezone changes."""
import asyncio
import os
import unittest
from contextlib import closing
from datetime import datetime, timezone
from unittest.mock import patch
from app import main, companies
from company_fixture import configuration
from test_scheduling_api import asgi_request
from . import _database_guard as guard
from ._schema_setup import isolated_schema


@unittest.skipUnless(os.environ.get('RUN_RECEPTIONIST_DB_INTEGRATION') == '1', 'Explicit isolated-database opt-in required')
class TimezoneBookingTests(unittest.TestCase):
    def test_timezone_change_overlap_and_independent_intervals(self):
        target = guard.Target()
        opened = []
        def connect():
            connection = target.connect(guard.APP_ROLE)
            opened.append(connection)
            return connection
        config = configuration(timezone='UTC', opening='00:00', closing='23:30', services={
            'consultation': {'duration_minutes':60,'keywords':['consultation']},
            'short': {'duration_minutes':30,'keywords':['short']}})
        with isolated_schema(target), patch.object(main,'get_db_connection',side_effect=connect), patch.object(
                main,'get_business_now',return_value=datetime(2030,1,1,6,tzinfo=timezone.utc)):
            tokens = {name:companies.provision(name,companies.CompanyConfig(**config))['credential']
                      for name in ('timezone-a','timezone-b')}
            def request(name, method, path, body):
                return asyncio.run(asgi_request(method,path,body,
                    [(b'authorization',('Bearer '+tokens[name]).encode())],timeout=180))[:2]
            def book(name, when, reason='consultation'):
                return request(name,'POST','/intake',{'name':'Synthetic','phone':'000',
                    'reason':reason,'preferred_time':when})
            first = book('timezone-a','2030-01-03T04:30:00Z')
            self.assertEqual((first[0],first[1]['status']),(200,'scheduled'))
            self.assertEqual(request('timezone-a','PUT','/companies/timezone-a',
                                    {**config,'timezone':'America/New_York'})[0],200)
            rejected = book('timezone-a','2030-01-03T00:00:00-05:00')
            self.assertEqual((rejected[0],rejected[1]['status']),(200,'slot_unavailable'))
            self.assertEqual(set(rejected[1]), {'status','service_type','industry','duration_minutes','priority','available_options'})
            with closing(connect()) as connection:
                rows = guard.query(connection,'SELECT scheduled_at,duration_minutes,scheduled_time FROM intake_requests WHERE tenant_id=%s',('timezone-a',))
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0][0],datetime(2030,1,3,4,30,tzinfo=timezone.utc))
                self.assertEqual(rows[0][1],60)
                self.assertEqual(datetime.fromisoformat(rows[0][2]),rows[0][0])
                connection.rollback()
            # Different tenant, same absolute reservation; also a separate interval
            # that becomes 23:00-23:30 on the previous local day.
            self.assertEqual(book('timezone-b','2030-01-03T04:00:00Z','short')[1]['status'],'scheduled')
            self.assertEqual(book('timezone-b','2030-01-03T04:30:00Z')[1]['status'],'scheduled')
            self.assertEqual(request('timezone-b','PUT','/companies/timezone-b',
                                    {**config,'timezone':'America/New_York'})[0],200)
            self.assertEqual(book('timezone-b','2030-01-03T00:30:00-05:00','short')[1]['status'],'scheduled')
            # Adjacent date and exact end boundary remain available.
            self.assertEqual(book('timezone-a','2030-01-03T00:30:00-05:00')[1]['status'],'scheduled')
            self.assertEqual(book('timezone-a','2030-01-04T00:30:00-05:00')[1]['status'],'scheduled')
            self.assertTrue(all(connection.closed for connection in opened))
