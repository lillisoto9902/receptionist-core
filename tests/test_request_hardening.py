"""Bounded raw HTTP input and sanitized failures without external services."""
import asyncio
import json
import unittest
from unittest.mock import patch
from app import main
from app.request_safety import RequestSafety
from test_scheduling_api import asgi_request


async def raw_request(body=b'', headers=(), path='/intake', application=None):
    output=[]
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST',
           'scheme':'http','path':path,'raw_path':path.encode(),'query_string':b'',
           'root_path':'','headers':list(headers),'server':('test.invalid',80),'client':('127.0.0.1',1)}
    delivered=False
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered=True
            return {'type':'http.request','body':body,'more_body':False}
        await asyncio.Event().wait()
    async def send(message):
        output.append(message)
    await (application or main.app)(scope,receive,send)
    return output[0]['status'],json.loads(output[1]['body'])


class RequestHardeningTests(unittest.TestCase):
    def test_malformed_json(self):
        self.assertEqual(asyncio.run(raw_request(b'{',[(b'content-type',b'application/json')])),(422,{'detail':'Invalid request'}))

    def test_duplicate_json_fields(self):
        for body in (b'{"tenant_id":"a","tenant_id":"b"}',b'{"nested":{"x":1,"x":2}}'):
            self.assertEqual(asyncio.run(raw_request(body,[(b'content-type',b'application/json')]))[0],422)

    def test_nonfinite_json(self):
        self.assertEqual(asyncio.run(raw_request(b'{"x":NaN}',[(b'content-type',b'application/json')]))[0],422)

    def test_body_limit_without_content_length(self):
        self.assertEqual(asyncio.run(raw_request(b'x'*65537))[0],413)

    def test_declared_body_limit(self):
        self.assertEqual(asyncio.run(raw_request(headers=[(b'content-length',b'999999')]))[0],413)

    def test_conflicting_content_lengths(self):
        self.assertEqual(asyncio.run(raw_request(headers=[(b'content-length',b'0'),(b'content-length',b'1')]))[0],400)

    def test_unsupported_content_type(self):
        self.assertEqual(asyncio.run(raw_request(b'{}',[(b'content-type',b'text/plain')]))[0],415)

    def test_duplicate_authorization(self):
        self.assertEqual(asyncio.run(raw_request(headers=[(b'authorization',b'Bearer a'),(b'authorization',b'Bearer b')]))[0],401)

    def test_malformed_bearer(self):
        for token in (b'Bearer a b',b'Bearer a, Bearer b',b'Bearer ',b'Basic a'):
            self.assertEqual(asyncio.run(raw_request(headers=[(b'authorization',token)]))[0],401)

    def test_duplicate_tenant_header(self):
        self.assertEqual(asyncio.run(raw_request(headers=[(b'x-tenant-id',b'a'),(b'x-tenant-id',b'a')]))[0],401)

    def test_internal_exception_sanitized(self):
        async def failing(scope,receive,send):
            raise RuntimeError('private SQL bearer database details')
        with self.assertLogs('receptionist.operations',level='INFO') as logs:
            response=asyncio.run(raw_request(application=RequestSafety(failing),path='/private-path'))
        self.assertEqual(response,(500,{'detail':'Internal server error'}))
        self.assertNotIn('private',str(logs.output))

    def test_health_security_headers(self):
        response=asyncio.run(asgi_request('GET','/health'))
        self.assertEqual(response[2][b'cache-control'],b'no-store')
        self.assertEqual(response[2][b'x-content-type-options'],b'nosniff')

    def test_docs_are_not_public(self):
        self.assertEqual(asyncio.run(asgi_request('GET','/openapi.json'))[0],404)

    def test_field_limits_and_nulls(self):
        for payload in ({'name':'','phone':'000','reason':'x'},
                        {'name':'x'*121,'phone':'000','reason':'x'},
                        {'name':'x','phone':None,'reason':'x'},
                        {'name':'x','phone':'000','reason':'x','unexpected':True}):
            with self.assertRaises(ValueError):
                main.IntakeRequest(**payload)

    def test_failure_then_valid_request(self):
        self.assertEqual(asyncio.run(raw_request(b'{',[(b'content-type',b'application/json')]))[0],422)
        self.assertEqual(asyncio.run(asgi_request('GET','/health'))[0],200)
