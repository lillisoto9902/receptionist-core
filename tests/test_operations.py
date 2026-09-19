"""Operational configuration, startup and connection recovery without network I/O."""
import asyncio
import os
import unittest
from unittest.mock import MagicMock, patch
from app import main, operations
from operations_fixture import environment
from test_scheduling_api import asgi_request


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.env = environment()
        self.enterContext(patch.dict(os.environ,self.env,clear=True))

    def test_explicit_isolated_configuration(self):
        self.assertEqual(operations.load_settings().port,55432)

    def test_missing_required_settings(self):
        for key in self.env:
            with patch.dict(os.environ,self.env,clear=True):
                del os.environ[key]
                with self.assertRaises(operations.ConfigurationError):
                    operations.load_settings()

    def test_empty_required_settings(self):
        for key in self.env:
            with patch.dict(os.environ,{key:''}):
                with self.assertRaises(operations.ConfigurationError):
                    operations.load_settings()

    def test_insecure_admin_configuration(self):
        for token in ('replace-with-local-dev-token','a'*64,'bad secret','é'*64):
            with patch.dict(os.environ,{'ADMIN_API_TOKEN':token}):
                with self.assertRaises(operations.ConfigurationError):
                    operations.load_settings()

    def test_target_mismatch_and_overrides_rejected(self):
        for changes in ({'RC_DATABASE_PORT':'5432'},{'RC_DATABASE_NAME':'other'},
                        {'RC_DATABASE_USER':'postgres'},{'RC_ENVIRONMENT':'unknown'},
                        {'PGSERVICE':'unapproved'}, {'DATABASE_URL':self.env['DATABASE_URL']+'?options=unsafe'},
                        {'DATABASE_URL':self.env['DATABASE_URL']+'?sslmode=disable&sslmode=require'}):
            with patch.dict(os.environ,changes):
                with self.assertRaises(operations.ConfigurationError):
                    operations.load_settings()

    def test_production_cannot_use_local_test_target(self):
        with patch.dict(os.environ,{'RC_ENVIRONMENT':'production'}):
            with self.assertRaises(operations.ConfigurationError):
                operations.load_settings()

    def test_secret_absent_from_settings_representation(self):
        settings = operations.load_settings()
        self.assertFalse(settings.password in repr(settings))


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ,environment(),clear=True))
        self.connection = MagicMock()
        self.connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (
            'receptionist_core_test','receptionist_core_test_app',180004,*([False]*9))
        self.driver = self.enterContext(patch.object(operations.psycopg2,'connect',return_value=self.connection))

    def test_bounded_acquisition_and_clean_transaction(self):
        self.assertIs(operations.connect(),self.connection)
        self.assertEqual(self.driver.call_args.kwargs['connect_timeout'],5)
        self.assertIn('statement_timeout=5000',self.driver.call_args.kwargs['options'])
        self.connection.set_session.assert_called_once_with(isolation_level='READ COMMITTED')
        self.connection.rollback.assert_called_once()

    def test_connection_failure_sanitized_and_recovers(self):
        self.driver.side_effect = [RuntimeError('private-driver-detail'),self.connection]
        with self.assertLogs('receptionist.operations',level='WARNING') as logs:
            with self.assertRaises(operations.DatabaseUnavailable) as caught:
                operations.connect()
        self.assertNotIn('private-driver-detail',str(caught.exception)+str(logs.output))
        self.assertIs(operations.connect(),self.connection)

    def test_identity_failure_closes_connection(self):
        self.connection.cursor.return_value.__enter__.return_value.fetchone.return_value = ('other',)
        with self.assertRaises(operations.DatabaseUnavailable):
            operations.connect()
        self.connection.close.assert_called_once()

    def test_elevated_role_rejected(self):
        self.connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (
            'receptionist_core_test','receptionist_core_test_app',180004,True,*([False]*8))
        with self.assertRaises(operations.DatabaseUnavailable):
            operations.connect()
        self.connection.close.assert_called_once()

    def test_readiness_failure_rolls_back_and_closes(self):
        self.connection.cursor.return_value.__enter__.return_value.execute.side_effect = RuntimeError('private')
        with self.assertRaises(RuntimeError):
            operations.check_ready(lambda:self.connection)
        self.connection.rollback.assert_called_once()
        self.connection.close.assert_called_once()

    def test_liveness_independent_and_readiness_recovers(self):
        with patch.object(operations,'check_ready',side_effect=[RuntimeError('private'),None]):
            self.assertEqual(asyncio.run(asgi_request('GET','/health'))[0],200)
            first = asyncio.run(asgi_request('GET','/ready'))
            self.assertEqual(first[:2],(503,{'ready':False}))
            self.assertEqual(asyncio.run(asgi_request('GET','/ready'))[:2],(200,{'ready':True}))

    def test_startup_fails_closed(self):
        async def start():
            async with main.lifespan(main.app):
                self.fail('Invalid startup accepted')
        with patch.object(operations,'check_ready',side_effect=RuntimeError('private')):
            with self.assertRaisesRegex(RuntimeError,'^Application startup validation failed$'):
                asyncio.run(start())

    def test_start_stop_restart_checks_readiness(self):
        async def start():
            async with main.lifespan(main.app):
                pass
        with patch.object(operations,'check_ready') as ready:
            asyncio.run(start())
            asyncio.run(start())
            self.assertEqual(ready.call_count,2)
