"""Three-tenant release workflow, real connector, rollback and lifespan restart."""
import asyncio
import os
import unittest
from contextlib import closing
from datetime import datetime, timezone
from unittest.mock import patch
from app import main, companies, operations
from company_fixture import configuration
from operations_fixture import environment
from test_scheduling_api import asgi_request
from . import _database_guard as guard
from ._schema_setup import isolated_schema


@unittest.skipUnless(os.environ.get('RUN_RECEPTIONIST_DB_INTEGRATION') == '1','Explicit isolated-database opt-in required')
class ReleaseCandidateTests(unittest.TestCase):
    def test_three_tenants_recovery_and_restart(self):
        target = guard.Target()
        # Public guard validates the runtime before exercising the real operational connector.
        with closing(target.connect(guard.APP_ROLE)) as verified:
            verified.rollback()
        env = environment()
        env['DATABASE_URL'] = target.urls[guard.APP_ROLE]
        opened = []
        def connect():
            connection = operations.connect()
            opened.append(connection)
            return connection
        configs = {}
        for name,zone,hours,duration,interval in (
                ('release-a','UTC',('09:00','17:00'),30,30),
                ('release-b','America/New_York',('08:00','16:00'),60,60),
                ('release-c','America/Denver',('07:00','15:00'),90,30)):
            configs[name] = configuration(business_name=name,timezone=zone,opening=hours[0],closing=hours[1],
                interval_minutes=interval,active=False,services={name:{'duration_minutes':duration,'keywords':[name]}})
        with isolated_schema(target), patch.dict(os.environ,env), patch.object(main,'get_db_connection',side_effect=connect), patch.object(
                main,'get_business_now',return_value=datetime(2030,1,1,6,tzinfo=timezone.utc)):
            def request(method,path,token=None,payload=None):
                headers = [(b'authorization',('Bearer '+token).encode())] if token else []
                return asyncio.run(asgi_request(method,path,payload,headers,timeout=120))[:2]
            admin = env['ADMIN_API_TOKEN']
            tokens = {}
            for name,config in configs.items():
                status,body = request('POST','/platform/companies/'+name,admin,config)
                self.assertEqual(status,200)
                tokens[name] = body['credential']
                self.assertEqual(request('GET','/settings',tokens[name])[0],401)
                self.assertEqual(request('PUT','/platform/companies/'+name,admin,{**config,'active':True})[0],200)
                body = request('GET','/companies/'+name,tokens[name])[1]
                self.assertEqual(body['configuration']['business_name'],name)
                self.assertEqual(body['configuration']['timezone'],config['timezone'])
            records = {}
            def payload(name,when='2030-01-03T15:00:00Z'):
                return {'name':'Synthetic','phone':'000','reason':name,'preferred_time':when}
            for name in configs:
                status,body = request('POST','/intake',tokens[name],payload(name))
                self.assertEqual((status,body['status']),(200,'scheduled'))
                records[name] = body['data']['id']
                self.assertEqual(request('GET','/intakes',tokens[name])[1]['count'],1)
            self.assertEqual(request('POST','/intake',tokens['release-a'],payload('release-a'))[1]['status'],'slot_unavailable')
            for other in ('release-b','release-c'):
                for method in ('GET','DELETE'):
                    self.assertEqual(request(method,'/intakes/'+str(records[other]),tokens['release-a'])[1]['status'],'not_found')
                self.assertEqual(request('PUT','/intakes/'+str(records[other])+'/status',tokens['release-a'],{'appointment_status':'cancelled'})[1]['status'],'not_found')
            self.assertEqual(request('POST','/platform/companies/forbidden',tokens['release-a'],configs['release-a'])[0],401)
            self.assertEqual(request('GET','/settings',admin)[0],401)
            self.assertEqual(request('GET','/settings?tenant_id=release-b',tokens['release-a'])[0],401)
            self.assertEqual(request('POST','/intake',tokens['release-a'],{**payload('release-a'),'reason':'unknown'})[0],422)
            self.assertEqual(request('PUT','/platform/companies/release-a',admin,{**configs['release-a'],'timezone':'invalid/zone'})[0],422)
            self.assertEqual(request('POST','/platform/companies/release-a',admin,configs['release-a'])[0],409)
            # Fail after PostgreSQL has executed an INSERT, before commit. Closing
            # the real connection must roll back that write, not just a mock call.
            class FailingCursor:
                def __init__(self,cursor): self.cursor=cursor
                def __getattr__(self,name): return getattr(self.cursor,name)
                def execute(self,sql,parameters=None):
                    self.cursor.execute(sql,parameters)
                    if 'INSERT INTO intake_requests' in sql:
                        raise RuntimeError('synthetic private database detail')
            class FailingConnection:
                def __init__(self,connection): self.connection=connection
                def __getattr__(self,name): return getattr(self.connection,name)
                def cursor(self): return FailingCursor(self.connection.cursor())
            def fail_connect(): return FailingConnection(connect())
            with patch.object(main,'get_db_connection',side_effect=fail_connect):
                self.assertEqual(request('POST','/intake',tokens['release-a'],payload('release-a','2030-01-04T15:00:00Z')),
                                 (503,{'detail':'Service unavailable'}))
            self.assertEqual(request('GET','/intakes',tokens['release-a'])[1]['count'],1)
            self.assertEqual(request('POST','/intake',tokens['release-a'],payload('release-a','2030-01-04T15:00:00Z'))[1]['status'],'scheduled')
            with patch.object(main,'get_db_connection',side_effect=operations.DatabaseUnavailable('private')):
                self.assertEqual(request('GET','/ready'),(503,{'ready':False}))
                self.assertEqual(request('GET','/settings',tokens['release-a']),(503,{'detail':'Service unavailable'}))
            self.assertEqual(request('GET','/ready'),(200,{'ready':True}))
            async def restart_cycle():
                async with main.lifespan(main.app):
                    result = await asgi_request('GET','/companies/release-a',headers=[(b'authorization',('Bearer '+tokens['release-a']).encode())],timeout=120)
                    self.assertEqual(result[0],200)
                    self.assertEqual(result[1]['configuration']['business_name'],'release-a')
            asyncio.run(restart_cycle())
            asyncio.run(restart_cycle())
            self.assertEqual(request('PUT','/platform/companies/release-c',admin,configs['release-c'])[0],200)
            self.assertEqual(request('GET','/settings',tokens['release-c'])[0],401)
            self.assertTrue(all(connection.closed for connection in opened))
