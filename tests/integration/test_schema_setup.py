"""Opt-in live tests; external preflight/startup/shutdown remain mandatory."""

import os
import unittest
from unittest.mock import patch

import psycopg2

from app import main
from . import _database_guard as guard
from ._schema_setup import BorrowedConnection, isolated_schema, relations


@unittest.skipUnless(os.environ.get('RUN_RECEPTIONIST_DB_INTEGRATION') == '1',
                     'Explicit isolated-database opt-in required')
class SchemaIntegrationTests(unittest.TestCase):
    def test_schema_lifecycle_runtime_and_privilege_boundaries(self):
        target = guard.Target()
        with isolated_schema(target):
            connection = target.connect(guard.APP_ROLE)
            try:
                guard.query(connection, "SET statement_timeout = '5s'")
                guard.query(connection, "SET lock_timeout = '2s'")
                columns = guard.query(connection, """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='intake_requests'
                    ORDER BY ordinal_position
                """)
                self.assertEqual([r[0] for r in columns], [
                    'id','name','phone','email','reason','preferred_time','source',
                    'scheduled_time','appointment_status','service_type','industry',
                    'duration_minutes','priority','created_at',
                ])
                self.assertEqual(guard.query(connection,
                    'SELECT count(*) FROM public.intake_requests'), [(0,)])
                guard.query(connection, """
                    INSERT INTO public.intake_requests
                    (name,phone,reason,scheduled_time,appointment_status,duration_minutes)
                    VALUES ('Synthetic','000','consultation','09:00','scheduled',30)
                """)
                with patch.object(main, 'get_db_connection',
                                  return_value=BorrowedConnection(connection)):
                    self.assertEqual(main.get_active_bookings(), [('09:00', 30)])
                    self.assertFalse(main.is_slot_available('09:00', 30))
                    self.assertTrue(main.is_slot_available('10:00', 30))
                guard.query(connection, "UPDATE public.intake_requests SET appointment_status='cancelled'")
                with patch.object(main, 'get_db_connection',
                                  return_value=BorrowedConnection(connection)):
                    self.assertEqual(main.get_active_bookings(), [])
                guard.query(connection, 'DELETE FROM public.intake_requests')
                connection.rollback()  # No synthetic record is committed.
                self.assertEqual(guard.query(connection,
                    'SELECT count(*) FROM public.intake_requests'), [(0,)])
                privileges = guard.query(connection, """
                    SELECT has_database_privilege(current_user,current_database(),'CREATE'),
                           has_database_privilege(current_user,current_database(),'TEMP'),
                           has_schema_privilege(current_user,'public','CREATE')
                """)
                self.assertEqual(privileges, [(False, False, False)])
                self.assertEqual(guard.query(connection, """
                    SELECT x.privilege_type FROM pg_class c
                    JOIN pg_namespace n ON n.oid=c.relnamespace
                    CROSS JOIN LATERAL aclexplode(c.relacl) x
                    WHERE n.nspname='public' AND x.grantee=0
                """), [])
                for statement in (
                    'CREATE TABLE public.forbidden_probe (id integer)',
                    'CREATE TEMP TABLE forbidden_probe (id integer)',
                    'ALTER TABLE public.intake_requests ADD COLUMN forbidden_probe integer',
                ):
                    connection.rollback()
                    code = None
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute(statement)
                    except psycopg2.Error as error:
                        code = error.pgcode
                    finally:
                        connection.rollback()
                    self.assertEqual(code, '42501')
            finally:
                connection.rollback()
                connection.close()
        connection = target.connect(guard.APP_ROLE)
        try:
            self.assertEqual(relations(connection), [])
        finally:
            connection.rollback()
            connection.close()
