"""Offline company boundary tests with generated synthetic credentials only."""
import hashlib
import secrets
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from app import companies, main
from company_fixture import configuration


class TenantAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.secret = 'synthetic-a.' + secrets.token_urlsafe(32)
        self.digest = hashlib.sha256(self.secret.encode()).hexdigest()
        self.query = self.enterContext(patch.object(companies, 'execute', return_value=[(configuration(), self.digest)]))

    def test_correct_credential_resolves_bound_tenant(self):
        with patch.object(companies.secrets, 'compare_digest', wraps=secrets.compare_digest) as comparison:
            result = companies.authenticate('Bearer ' + self.secret)
        self.assertEqual(result['tenant_id'], 'synthetic-a')
        self.assertTrue(comparison.called)
        self.assertNotIn('credential', result)

    def test_second_credential_resolves_second_tenant(self):
        token = 'synthetic-b.' + secrets.token_urlsafe(32)
        self.query.return_value = [(configuration(), hashlib.sha256(token.encode()).hexdigest())]
        self.assertEqual(companies.authenticate('Bearer ' + token)['tenant_id'], 'synthetic-b')

    def test_wrong_secret_rejected(self):
        with self.assertRaises(HTTPException) as caught:
            companies.authenticate('Bearer synthetic-a.' + secrets.token_urlsafe(32))
        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(caught.exception.detail, 'Unauthorized')

    def test_missing_and_malformed_credentials_do_not_query(self):
        for value in (None, '', 'Basic invalid', 'Bearer invalid', 'Bearer é.invalid'):
            with self.assertRaises(HTTPException):
                companies.authenticate(value)
        self.query.assert_not_called()

    def test_unknown_credential_fails_closed(self):
        self.query.return_value = []
        with self.assertRaises(HTTPException):
            companies.authenticate('Bearer ' + self.secret)

    def test_inactive_company_rejected(self):
        self.query.return_value = [(configuration(active=False), self.digest)]
        with self.assertRaises(HTTPException) as caught:
            companies.authenticate('Bearer ' + self.secret)
        self.assertEqual(caught.exception.status_code, 401)

    def test_invalid_persisted_configuration_fails_closed(self):
        self.query.return_value = [({}, self.digest)]
        with self.assertRaises(HTTPException) as caught:
            companies.authenticate('Bearer ' + self.secret)
        self.assertEqual(caught.exception.status_code, 503)

    def test_missing_internal_context_has_no_fallback(self):
        marker = companies.context.set(None)
        try:
            with self.assertRaises(HTTPException):
                companies.tenant_id()
        finally:
            companies.context.reset(marker)


class ConfigurationTests(unittest.TestCase):
    def test_valid_company(self):
        self.assertTrue(companies.CompanyConfig(**configuration()).active)

    def test_timezone_invalid(self):
        with self.assertRaises(ValidationError):
            companies.CompanyConfig(**configuration(timezone='Invalid/Zone'))

    def test_hours_invalid(self):
        for change in ({'opening':'18:00'}, {'opening':'9:00'}, {'closing':'25:00'}):
            with self.assertRaises(ValidationError):
                companies.CompanyConfig(**configuration(**change))

    def test_intervals_invalid(self):
        for value in (0, -1, True, '30', 241):
            with self.assertRaises(ValidationError):
                companies.CompanyConfig(**configuration(interval_minutes=value))

    def test_service_duration_invalid(self):
        for value in (0, -1, True, '30', 1000):
            config = configuration()
            config['services']['consultation']['duration_minutes'] = value
            with self.assertRaises(ValidationError):
                companies.CompanyConfig(**config)

    def test_conflicting_services_rejected(self):
        config = configuration()
        config['services']['haircut']['keywords'] = ['consultation']
        with self.assertRaises(ValidationError):
            companies.CompanyConfig(**config)

    def test_unknown_fields_rejected(self):
        with self.assertRaises(ValidationError):
            companies.CompanyConfig(**configuration(tenant_id='other'))


class ProvisioningTests(unittest.TestCase):
    def test_only_digest_is_persisted(self):
        with patch.object(companies, 'execute', return_value=[('synthetic-a',)]) as query:
            result = companies.provision('synthetic-a', companies.CompanyConfig(**configuration()))
        self.assertTrue(result['credential'] not in str(query.call_args))
        self.assertEqual(len(query.call_args.args[1][2]), 64)

    def test_duplicate_does_not_rotate_credential(self):
        with patch.object(companies, 'execute', return_value=[]):
            with self.assertRaises(HTTPException) as caught:
                companies.provision('synthetic-a', companies.CompanyConfig(**configuration()))
        self.assertEqual(caught.exception.status_code, 409)

    def test_invalid_identity_does_not_write(self):
        with patch.object(companies, 'execute') as query:
            for identifier in ('', 'UPPER', '../other', 'a; DROP TABLE companies'):
                with self.assertRaises(HTTPException):
                    companies.provision(identifier, companies.CompanyConfig(**configuration()))
        query.assert_not_called()

    def test_database_error_closes_connection_and_sanitizes(self):
        from unittest.mock import MagicMock
        connection = MagicMock()
        connection.cursor.return_value.execute.side_effect = RuntimeError('synthetic private detail')
        with patch.object(main, 'get_db_connection', return_value=connection):
            with self.assertRaises(HTTPException) as caught:
                companies.execute('SELECT 1')
        self.assertEqual(caught.exception.detail, 'Service unavailable')
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()


class TenantIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tokens = {name: name + '.' + secrets.token_urlsafe(32) for name in ('synthetic-a','synthetic-b')}
        def lookup(statement, params=(), **kwargs):
            name = params[0]
            token = self.tokens.get(name)
            return [(configuration(),hashlib.sha256(token.encode()).hexdigest())] if token else []
        self.enterContext(patch.object(companies, 'execute', side_effect=lookup))

    def request(self, method, path, tenant='synthetic-a', payload=None, headers=()):
        import asyncio
        from test_scheduling_api import asgi_request
        return asyncio.run(asgi_request(method,path,payload,[(b'authorization', ('Bearer '+self.tokens[tenant]).encode()), *headers]))

    def test_each_company_reads_only_own_configuration(self):
        for tenant in self.tokens:
            status, body, _ = self.request('GET','/companies/'+tenant,tenant)
            self.assertEqual(status,200)
            self.assertEqual(body['tenant_id'],tenant)

    def test_bidirectional_path_impersonation_denied(self):
        for tenant, other in (('synthetic-a','synthetic-b'),('synthetic-b','synthetic-a')):
            for method in ('GET','PUT'):
                status,body,_=self.request(method,'/companies/'+other,tenant,configuration() if method=='PUT' else None)
                self.assertEqual((status,body),(401,{'detail':'Unauthorized'}))

    def test_query_and_header_impersonation_denied(self):
        for path,headers in (('/settings?tenant_id=synthetic-b',()),('/settings',[(b'x-tenant-id',b'synthetic-b')]),('/settings?tenant_id=synthetic-a&tenant_id=synthetic-b',())):
            self.assertEqual(self.request('GET',path,headers=headers)[0],401)

    def test_body_cannot_change_intake_owner(self):
        self.assertEqual(self.request('POST','/intake',payload={'tenant_id':'synthetic-b','name':'Synthetic','phone':'000','reason':'consultation','preferred_time':'09:00'})[0],401)

    def test_tenant_cannot_provision(self):
        with patch.dict(main.os.environ,{'ADMIN_API_TOKEN':secrets.token_urlsafe(32)}):
            self.assertEqual(self.request('POST','/platform/companies/synthetic-b',payload=configuration())[0],401)

    def test_admin_is_not_tenant_fallback(self):
        import asyncio
        from test_scheduling_api import asgi_request
        token=secrets.token_urlsafe(32)
        with patch.dict(main.os.environ,{'ADMIN_API_TOKEN':token}):
            status,body,_=asyncio.run(asgi_request('GET','/settings',headers=[(b'authorization',('Bearer '+token).encode())]))
        self.assertEqual((status,body),(401,{'detail':'Unauthorized'}))

    def test_request_context_is_reset(self):
        self.request('GET','/settings')
        self.assertIsNone(companies.context.get())
