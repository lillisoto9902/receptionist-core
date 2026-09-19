"""Live startup/readiness contract against the unchanged application initializer."""
import asyncio
import os
import unittest
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from psycopg2 import sql
from app import main, operations
from company_fixture import configuration
from operations_fixture import environment
from test_scheduling_api import asgi_request
from . import _database_guard as guard
from ._schema_setup import isolated_schema


@unittest.skipUnless(os.environ.get('RUN_RECEPTIONIST_DB_INTEGRATION') == '1',
                     'Explicit isolated-database opt-in required')
class ReadinessSchemaTests(unittest.TestCase):
    @contextmanager
    def live(self):
        target = guard.Target()
        # The unchanged public guard binds both connections to the approved cluster.
        with closing(target.connect(guard.APP_ROLE)) as verified:
            verified.rollback()
        env = environment()
        env['DATABASE_URL'] = target.urls[guard.APP_ROLE]
        opened = []

        def connect():
            connection = operations.connect()
            opened.append(connection)
            return connection

        with isolated_schema(target), closing(target.connect(guard.MIGRATOR_ROLE)) as migration:
            guard.query(migration, "SET statement_timeout='5s'")
            guard.query(migration, "SET lock_timeout='2s'")
            migration.commit()
            with patch.dict(os.environ, env), patch.object(main, 'get_db_connection', side_effect=connect), \
                    patch.object(main, 'get_business_now', return_value=datetime(2030, 1, 1, 6, tzinfo=timezone.utc)):
                try:
                    yield migration, env['ADMIN_API_TOKEN']
                finally:
                    self.assertTrue(all(connection.closed for connection in opened))

    def request(self, method, path, token=None, payload=None):
        headers = [(b'authorization', ('Bearer ' + token).encode())] if token else []
        return asyncio.run(asgi_request(method, path, payload, headers, timeout=120))[:2]

    def startup(self):
        async def start():
            async with main.lifespan(main.app):
                pass
        asyncio.run(start())

    def assert_rejected(self):
        self.assertEqual(self.request('GET', '/ready'), (503, {'ready': False}))
        with self.assertRaisesRegex(RuntimeError, '^Application startup validation failed$'):
            self.startup()

    @contextmanager
    def changed(self, migration, forward, reverse):
        try:
            guard.query(migration, forward)
            migration.commit()
        except Exception:
            migration.rollback()
            raise
        try:
            yield
        finally:
            migration.rollback()
            guard.query(migration, reverse)
            migration.commit()

    def test_name_rename_rejects_readiness_and_startup_then_recovers(self):
        with self.live() as (migration, admin):
            self.startup()
            self.assertEqual(self.request('GET', '/ready'), (200, {'ready': True}))
            config = configuration(timezone='UTC', services={
                'consultation': {'duration_minutes': 30, 'keywords': ['consultation']}})
            status, body = self.request('POST', '/platform/companies/schema-review', admin, config)
            self.assertEqual(status, 200)
            tenant = body['credential']
            payload = {'name': 'Synthetic', 'phone': '000', 'reason': 'consultation',
                       'preferred_time': '2030-01-03T09:00:00Z'}
            status, body = self.request('POST', '/intake', tenant, payload)
            self.assertEqual((status, body['status']), (200, 'scheduled'))
            with self.changed(migration,
                    'ALTER TABLE public.intake_requests RENAME COLUMN name TO review_missing_name',
                    'ALTER TABLE public.intake_requests RENAME COLUMN review_missing_name TO name'):
                self.assert_rejected()
                # A pre-existing process remains fail-safe; its readiness is now false.
                self.assertEqual(self.request('GET', '/intakes', tenant),
                                 (503, {'detail': 'Service unavailable'}))
            self.startup()
            self.assertEqual(self.request('GET', '/ready'), (200, {'ready': True}))
            self.assertEqual(self.request('GET', '/intakes', tenant)[1]['count'], 1)
            status, body = self.request('POST', '/intake', tenant,
                                       {**payload, 'preferred_time': '2030-01-04T09:00:00Z'})
            self.assertEqual((status, body['status']), (200, 'scheduled'))

    def test_every_initializer_column_is_covered(self):
        with self.live() as (migration, _):
            # Enumerate the actual initializer's schema, not the validator's list.
            rows = guard.query(migration, '''SELECT c.relname,a.attname,
                format_type(a.atttypid,a.atttypmod),a.attnotnull
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                JOIN pg_attribute a ON a.attrelid=c.oid
                WHERE n.nspname='public' AND c.relname IN ('companies','intake_requests')
                AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum''')
            migration.rollback()
            actual = {}
            for table, column, kind, required in rows:
                actual.setdefault(table, {})[column] = (kind, required)
            self.assertEqual(actual, operations.REQUIRED_COLUMNS)
            for table, column, _, _ in rows:
                with self.subTest(table=table, column=column):
                    forward = sql.SQL('ALTER TABLE public.{} RENAME COLUMN {} TO review_missing_column').format(
                        sql.Identifier(table), sql.Identifier(column))
                    reverse = sql.SQL('ALTER TABLE public.{} RENAME COLUMN review_missing_column TO {}').format(
                        sql.Identifier(table), sql.Identifier(column))
                    with self.changed(migration, forward, reverse):
                        self.assert_rejected()
            self.assertEqual(self.request('GET', '/ready'), (200, {'ready': True}))

    def test_incompatible_tables_types_keys_and_defaults_are_rejected(self):
        with self.live() as (migration, _):
            mutations = [
                ('ALTER TABLE public.intake_requests ADD COLUMN review_required text NOT NULL',
                 'ALTER TABLE public.intake_requests DROP COLUMN review_required'),
                ('ALTER TABLE public.companies RENAME TO review_missing_companies',
                 'ALTER TABLE public.review_missing_companies RENAME TO companies'),
                ('ALTER TABLE public.intake_requests RENAME TO review_missing_intakes',
                 'ALTER TABLE public.review_missing_intakes RENAME TO intake_requests'),
                ('ALTER TABLE public.intake_requests ALTER COLUMN scheduled_at TYPE timestamp without time zone',
                 'ALTER TABLE public.intake_requests ALTER COLUMN scheduled_at TYPE timestamp with time zone'),
                ('ALTER TABLE public.companies ALTER COLUMN configuration TYPE text USING configuration::text',
                 'ALTER TABLE public.companies ALTER COLUMN configuration TYPE jsonb USING configuration::jsonb'),
                ('ALTER TABLE public.intake_requests ALTER COLUMN duration_minutes TYPE text USING duration_minutes::text',
                 'ALTER TABLE public.intake_requests ALTER COLUMN duration_minutes TYPE integer USING duration_minutes::integer'),
                ('ALTER TABLE public.intake_requests ALTER COLUMN scheduled_at DROP NOT NULL',
                 'ALTER TABLE public.intake_requests ALTER COLUMN scheduled_at SET NOT NULL'),
                ('ALTER TABLE public.intake_requests ALTER COLUMN email SET NOT NULL',
                 'ALTER TABLE public.intake_requests ALTER COLUMN email DROP NOT NULL'),
                ('ALTER TABLE public.intake_requests DROP CONSTRAINT intake_requests_pkey',
                 'ALTER TABLE public.intake_requests ADD CONSTRAINT intake_requests_pkey PRIMARY KEY (id)'),
                ('ALTER TABLE public.companies DROP CONSTRAINT companies_credential_digest_key',
                 'ALTER TABLE public.companies ADD CONSTRAINT companies_credential_digest_key UNIQUE (credential_digest)'),
                ('ALTER TABLE public.intake_requests DROP CONSTRAINT intake_requests_tenant_id_fkey',
                 'ALTER TABLE public.intake_requests ADD CONSTRAINT intake_requests_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.companies(tenant_id)'),
                ('ALTER TABLE public.intake_requests ALTER COLUMN id DROP DEFAULT',
                 "ALTER TABLE public.intake_requests ALTER COLUMN id SET DEFAULT nextval('public.intake_requests_id_seq'::regclass)"),
                ('ALTER TABLE public.intake_requests ALTER COLUMN created_at DROP DEFAULT',
                 'ALTER TABLE public.intake_requests ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP'),
                ('ALTER SEQUENCE public.intake_requests_id_seq RENAME TO review_missing_sequence',
                 'ALTER SEQUENCE public.review_missing_sequence RENAME TO intake_requests_id_seq'),
            ]
            for index, (forward, reverse) in enumerate(mutations):
                with self.subTest(mutation=index), self.changed(migration, forward, reverse):
                    self.assert_rejected()
            self.startup()
            self.assertEqual(self.request('GET', '/ready'), (200, {'ready': True}))
