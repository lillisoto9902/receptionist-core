"""Bounded ASGI ingress and metadata-only operational logging; not rate limiting."""
import asyncio
import json
import logging
import re
from urllib.parse import parse_qsl
from starlette.responses import JSONResponse

logger = logging.getLogger('receptionist.operations')
MAX_BODY = 65536


def bearer_valid(value):
    return isinstance(value, str) and re.fullmatch(r'Bearer [A-Za-z0-9._~-]{1,512}', value) is not None


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


class RequestSafety:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        started = False
        dispatched = False
        status = 500
        async def safe_send(message):
            nonlocal started, status
            if message['type'] == 'http.response.start':
                started = True
                status = message['status']
                message = {**message, 'headers': [*message.get('headers', []),
                    (b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff')]}
            await send(message)
        async def reject(code, detail):
            await JSONResponse({'detail': detail}, status_code=code,
                headers={'WWW-Authenticate':'Bearer'} if code == 401 else None)(scope, receive, safe_send)
        try:
            headers = scope.get('headers', [])
            if len(scope.get('path', '')) > 2048 or len(scope.get('query_string', b'')) > 2048 or sum(len(k)+len(v) for k,v in headers) > 16384:
                return await reject(413, 'Request too large')
            auth = [v for k,v in headers if k.lower() == b'authorization']
            tenant = [v for k,v in headers if k.lower() == b'x-tenant-id']
            query = parse_qsl(scope.get('query_string', b'').decode('ascii'), max_num_fields=100)
            if len(auth) > 1 or (auth and not bearer_valid(auth[0].decode('latin1'))) or len(tenant) > 1 or sum(k=='tenant_id' for k,v in query) > 1:
                return await reject(401, 'Unauthorized')
            for name in (b'content-length', b'content-type'):
                if sum(k.lower()==name for k,v in headers) > 1:
                    return await reject(400, 'Invalid request')
            lengths = [v for k,v in headers if k.lower()==b'content-length']
            if lengths and (not lengths[0].isdigit() or int(lengths[0]) > MAX_BODY):
                return await reject(413, 'Request too large')
            body = bytearray()
            deadline = asyncio.get_running_loop().time() + 5
            while True:
                message = await asyncio.wait_for(receive(), max(0, deadline-asyncio.get_running_loop().time()))
                if message['type'] != 'http.request':
                    return
                body.extend(message.get('body', b''))
                if len(body) > MAX_BODY:
                    return await reject(413, 'Request too large')
                if not message.get('more_body', False):
                    break
            if lengths and int(lengths[0]) != len(body):
                return await reject(400, 'Invalid request')
            if body:
                content_type = next((v.split(b';')[0].strip().lower() for k,v in headers if k.lower()==b'content-type'), b'')
                if content_type != b'application/json':
                    return await reject(415, 'JSON required')
                json.loads(body, object_pairs_hook=unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            delivered = False
            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type':'http.request','body':bytes(body),'more_body':False}
                return await receive()
            dispatched = True
            await self.app(scope, replay, safe_send)
        except asyncio.TimeoutError:
            if not started:
                await reject(408, 'Request timed out')
        except (ValueError, UnicodeError, RecursionError):
            if not started:
                if dispatched:
                    logger.error('request_failed category=internal')
                await reject(500 if dispatched else 422, 'Internal server error' if dispatched else 'Invalid request')
        except Exception:
            logger.error('request_failed category=internal')
            if not started:
                await reject(500, 'Internal server error')
        finally:
            method = scope.get('method')
            method = method if method in ('GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS') else 'OTHER'
            route = getattr(scope.get('route'), 'path', 'unmatched')
            logger.info('request method=%s route=%s status=%d', method, route, status)
