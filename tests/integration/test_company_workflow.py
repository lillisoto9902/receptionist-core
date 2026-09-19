"""Real authenticated two-company workflow against the guarded isolated database."""
import asyncio
import io
import os
import secrets
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from unittest.mock import patch

from app import main
from company_fixture import configuration
from test_scheduling_api import asgi_request
from . import _database_guard as guard
from ._schema_setup import isolated_schema


@unittest.skipUnless(os.environ.get('RUN_RECEPTIONIST_DB_INTEGRATION') == '1',
                     'Explicit isolated-database opt-in required')
class CompanyWorkflowTests(unittest.TestCase):
    def test_authenticated_provisioning_persistence_and_isolation(self):
        target = guard.Target()
        admin = secrets.token_urlsafe(32)
        output = io.StringIO()
        opened = []

        def connect():
            connection = target.connect(guard.APP_ROLE)
            opened.append(connection)
            return connection

        def request(method, path, token, payload=None):
            return asyncio.run(asgi_request(method, path, payload,
                [(b'authorization', ('Bearer ' + token).encode())], timeout=120))[:2]

        with isolated_schema(target), patch.object(main, 'get_db_connection', side_effect=connect), \
                patch.dict(os.environ, {'ADMIN_API_TOKEN': admin}), \
                patch.object(main, 'get_business_now', return_value=datetime(2030,1,2,6,tzinfo=timezone.utc)), \
                redirect_stdout(output), redirect_stderr(output):
            configs = {
                'synthetic-a': configuration(timezone='UTC',opening='09:00',closing='12:00',services={
                    'consultation': {'duration_minutes':30,'keywords':['consultation'],'industry':'general','priority':'normal'}}),
                'synthetic-b': configuration(timezone='UTC',opening='10:00',closing='14:00',interval_minutes=60,services={
                    'consultation': {'duration_minutes':60,'keywords':['consultation'],'industry':'general','priority':'normal'}}),
            }
            tokens = {}
            for name, config in configs.items():
                status, body = request('POST', '/platform/companies/'+name, admin, config)
                self.assertEqual(status,200)
                tokens[name] = body['credential']
                self.assertEqual(request('POST','/platform/companies/'+name,admin,config)[0],409)
                # Each request opens fresh authenticated connections: persistence
                # is demonstrated without a process-memory configuration cache.
                status, body = request('GET','/companies/'+name,tokens[name])
                self.assertEqual(status,200)
                self.assertEqual(body['configuration']['opening'],config['opening'])
            for name, other in (('synthetic-a','synthetic-b'),('synthetic-b','synthetic-a')):
                self.assertEqual(request('GET','/companies/'+other,tokens[name])[0],401)
                self.assertEqual(request('PUT','/companies/'+other,tokens[name],configs[other])[0],401)
                self.assertEqual(request('POST','/platform/companies/forbidden',tokens[name],configs[name])[0],401)
                self.assertEqual(request('GET','/settings?tenant_id='+other,tokens[name])[0],401)
            payload = {'name':'Synthetic','phone':'000','reason':'consultation','preferred_time':'09:00'}
            self.assertEqual(request('POST','/intake',tokens['synthetic-a'],{**payload,'tenant_id':'synthetic-b'})[0],401)
            status, accepted = request('POST','/intake',tokens['synthetic-a'],payload)
            self.assertEqual((status,accepted['status']),(200,'scheduled'))
            record_id = accepted['data']['id']
            status, declined = request('POST','/intake',tokens['synthetic-b'],payload)
            self.assertEqual(declined['status'],'slot_unavailable')
            payload['preferred_time'] = '10:00'
            self.assertEqual(request('POST','/intake',tokens['synthetic-b'],payload)[1]['status'],'scheduled')
            for name in tokens:
                status, body = request('GET','/intakes',tokens[name])
                self.assertEqual(body['count'],1)
            self.assertEqual(request('GET',f'/intakes/{record_id}',tokens['synthetic-b'])[1]['status'],'not_found')
            self.assertEqual(request('PUT',f'/intakes/{record_id}/status',tokens['synthetic-b'],{'appointment_status':'cancelled'})[1]['status'],'not_found')
            self.assertEqual(request('DELETE',f'/intakes/{record_id}',tokens['synthetic-b'])[1]['status'],'not_found')
            self.assertEqual(request('GET',f'/intakes/{record_id}',tokens['synthetic-a'])[1]['status'],'ok')
            self.assertEqual(request('POST','/availability',tokens['synthetic-a'],{'reason':'unknown'})[0],422)
            self.assertEqual(request('GET','/settings',admin)[0],401)
            inactive = {**configs['synthetic-a'], 'active':False}
            self.assertEqual(request('PUT','/platform/companies/synthetic-a',admin,inactive)[0],200)
            self.assertEqual(request('GET','/settings',tokens['synthetic-a'])[0],401)
            self.assertEqual(request('PUT','/platform/companies/synthetic-a',admin,configs['synthetic-a'])[0],200)
            self.assertEqual(request('GET','/settings',tokens['synthetic-a'])[0],200)
            self.assertTrue(all(connection.closed for connection in opened))
            self.assertEqual(output.getvalue(),'')
