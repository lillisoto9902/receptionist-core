"""Concurrent real HTTP/application admissions, coordinated before row locking."""
import asyncio
import os
import threading
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import patch

from app import main, companies
from company_fixture import configuration
from test_scheduling_api import asgi_request
from . import _database_guard as guard
from ._schema_setup import isolated_schema


@unittest.skipUnless(os.environ.get('RUN_RECEPTIONIST_DB_INTEGRATION') == '1', 'Explicit isolated-database opt-in required')
class BookingAtomicityTests(unittest.TestCase):
    def test_concurrency_dates_tenants_and_readback(self):
        target=guard.Target()
        config=companies.CompanyConfig(**configuration(timezone='UTC',services={
            'consultation':{'duration_minutes':60,'keywords':['consultation'],'industry':'general','priority':'normal'}}))
        opened=[]
        def connect():
            connection=target.connect(guard.APP_ROLE)
            opened.append(connection)
            return connection
        with isolated_schema(target), patch.object(main,'get_db_connection',side_effect=connect), \
                patch.object(main,'get_business_now',return_value=datetime(2030,1,2,6,tzinfo=timezone.utc)):
            tokens={name:companies.provision(name,config)['credential'] for name in ('atomic-a','atomic-b')}
            def book(name,when):
                return asyncio.run(asgi_request('POST','/intake',
                    {'name':'Synthetic','phone':'000','reason':'consultation','preferred_time':when},
                    [(b'authorization',('Bearer '+tokens[name]).encode())],timeout=120))[:2]
            def concurrent(requests):
                barrier=threading.Barrier(2)
                original=main.get_active_bookings
                def lookup(reference_time=None,connection=None,exclude_id=None):
                    rows=original(reference_time,connection,exclude_id)
                    # Both real prechecks see the free slot. No serialization is
                    # imposed here; database admission must resolve the race.
                    if connection is None:
                        barrier.wait(timeout=60)
                    return rows
                with patch.object(main,'get_active_bookings',side_effect=lookup), ThreadPoolExecutor(max_workers=2) as pool:
                    futures=[pool.submit(book,*request) for request in requests]
                    return [future.result(timeout=180) for future in futures]
            when='2030-01-03T09:00:00+00:00'
            results=concurrent([('atomic-a',when),('atomic-a',when)])
            self.assertEqual([r[0] for r in results],[200,200])
            self.assertEqual(sorted(r[1]['status'] for r in results),['scheduled','slot_unavailable'])
            self.assertEqual(book('atomic-a','2030-01-04T09:00:00+00:00')[1]['status'],'scheduled')
            self.assertEqual(book('atomic-b',when)[1]['status'],'scheduled')
            self.assertEqual(book('atomic-a','2030-01-03T09:30:00+00:00')[1]['status'],'slot_unavailable')
            self.assertEqual(book('atomic-a','2030-01-03T10:00:00+00:00')[1]['status'],'scheduled')
            other_date='2030-01-05T09:00:00+00:00'
            self.assertTrue(all(r[1]['status']=='scheduled' for r in concurrent([('atomic-a',other_date),('atomic-b',other_date)])))
            with closing(connect()) as connection:
                try:
                    rows=guard.query(connection,'SELECT tenant_id,scheduled_at,scheduled_time,preferred_time FROM intake_requests ORDER BY tenant_id,scheduled_at')
                    self.assertEqual(len(rows),6)
                    self.assertEqual(sum(name=='atomic-a' and instant==datetime(2030,1,3,9,tzinfo=timezone.utc) for name,instant,_,_ in rows),1)
                    self.assertEqual(sum(name=='atomic-b' and instant==datetime(2030,1,3,9,tzinfo=timezone.utc) for name,instant,_,_ in rows),1)
                    for _,instant,scheduled,preferred in rows:
                        self.assertEqual(datetime.fromisoformat(scheduled),instant)
                        self.assertEqual(preferred,scheduled)
                finally:
                    connection.rollback()
                    connection.close()
            self.assertTrue(all(c.closed for c in opened))
            # Reinstating an old reservation must obey the same admission lock.
            connection=connect()
            try:
                original_id=guard.query(connection,
                    'SELECT id FROM intake_requests WHERE tenant_id=%s AND scheduled_at=%s',
                    ('atomic-a',datetime(2030,1,3,9,tzinfo=timezone.utc)))[0][0]
            finally:
                connection.rollback()
                connection.close()
            def change_status(status):
                return asyncio.run(asgi_request('PUT',f'/intakes/{original_id}/status',
                    {'appointment_status':status},[(b'authorization',('Bearer '+tokens['atomic-a']).encode())],timeout=120))[:2]
            self.assertEqual(change_status('cancelled')[1]['status'],'ok')
            self.assertEqual(book('atomic-a',when)[1]['status'],'scheduled')
            self.assertEqual(change_status('scheduled')[1]['status'],'slot_unavailable')
            connection=connect()
            try:
                self.assertEqual(guard.query(connection,
                    "SELECT count(*) FROM intake_requests WHERE tenant_id=%s AND scheduled_at=%s AND appointment_status='scheduled'",
                    ('atomic-a',datetime(2030,1,3,9,tzinfo=timezone.utc))),[(1,)])
            finally:
                connection.rollback()
                connection.close()
            self.assertTrue(all(c.closed for c in opened))
