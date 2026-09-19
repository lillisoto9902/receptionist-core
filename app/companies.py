"""Persistent company configuration and the existing bearer-token boundary."""

import hashlib
import json
import re
import secrets
from contextlib import closing
from contextvars import ContextVar
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


IDENTIFIER = re.compile(r'[a-z][a-z0-9-]{0,62}\Z')
context = ContextVar('authenticated_company', default=None)


class Service(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    duration_minutes: int = Field(ge=1, le=1440)
    keywords: list[str] = Field(min_length=1, max_length=20)
    industry: str = Field(default='general', min_length=1, max_length=80)
    priority: str = Field(default='normal', pattern=r'^(low|normal|high)$')

    @field_validator('keywords')
    @classmethod
    def keywords_valid(cls, value):
        normalized = [word.strip().lower() for word in value]
        if any(not word or len(word) > 80 for word in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError('Invalid keywords')
        return normalized


class CompanyConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    business_name: str = Field(min_length=1, max_length=120)
    contact_email: str = Field(default='', max_length=254)
    contact_phone: str = Field(default='', max_length=40)
    greeting: str = Field(default='How can we help?', min_length=1, max_length=500)
    timezone: str
    opening: str = Field(pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
    closing: str = Field(pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
    interval_minutes: int = Field(ge=1, le=240)
    services: dict[str, Service] = Field(min_length=1, max_length=50)
    active: bool = False
    auto_confirm: bool = False
    confirmation_required: bool = True
    booking_lead_time_hours: int = Field(default=2, ge=0, le=8760)
    max_advance_booking_days: int = Field(default=30, ge=1, le=365)
    cancellation_window_hours: int = Field(default=24, ge=0, le=8760)

    @model_validator(mode='after')
    def validate_rules(self):
        try:
            ZoneInfo(self.timezone)
        except Exception:
            raise ValueError('Invalid timezone') from None
        if not self.business_name.strip() or self.opening >= self.closing:
            raise ValueError('Invalid business configuration')
        def minutes(value):
            hour, minute = map(int, value.split(':'))
            return hour * 60 + minute
        span = minutes(self.closing) - minutes(self.opening)
        if self.interval_minutes > span:
            raise ValueError('Invalid interval')
        keywords = []
        for name, service in self.services.items():
            if not IDENTIFIER.fullmatch(name) or service.duration_minutes > span:
                raise ValueError('Invalid service')
            keywords.extend(service.keywords)
        if len(set(keywords)) != len(keywords):
            raise ValueError('Conflicting service keywords')
        return self


def current():
    company = context.get()
    if company is None:
        raise HTTPException(401, 'Unauthorized', headers={'WWW-Authenticate': 'Bearer'})
    return company


def tenant_id():
    return current()['tenant_id']


def denied():
    return HTTPException(401, 'Unauthorized', headers={'WWW-Authenticate': 'Bearer'})


def execute(statement, parameters=(), write=False):
    from app import main
    try:
        with closing(main.get_db_connection()) as connection:
            try:
                with closing(connection.cursor()) as cursor:
                    cursor.execute(statement, parameters)
                    rows = cursor.fetchall() if cursor.description else []
                if write:
                    connection.commit()
                return rows
            finally:
                connection.rollback()
    except Exception:
        raise HTTPException(503, 'Service unavailable') from None


def authenticate(authorization):
    if not authorization or not authorization.startswith('Bearer '):
        raise denied()
    token = authorization[7:]
    parts = token.split('.')
    if len(parts) != 2 or not IDENTIFIER.fullmatch(parts[0]) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', parts[1]):
        raise denied()
    rows = execute('SELECT configuration, credential_digest FROM companies WHERE tenant_id = %s', (parts[0],))
    digest = hashlib.sha256(token.encode('ascii')).hexdigest()
    expected = rows[0][1] if rows else '0' * 64
    matched = secrets.compare_digest(digest, expected)
    if not rows or not matched:
        raise denied()
    try:
        configuration = CompanyConfig.model_validate(rows[0][0]).model_dump()
    except Exception:
        raise HTTPException(503, 'Service unavailable') from None
    if not configuration['active']:
        raise denied()
    return {'tenant_id': parts[0], 'configuration': configuration}


async def require_tenant(request: Request):
    company = authenticate(request.headers.get('authorization'))
    supplied = request.query_params.getlist('tenant_id') + request.headers.getlist('x-tenant-id')
    if 'tenant_id' in request.path_params:
        supplied.append(request.path_params['tenant_id'])
    if request.method in ('POST', 'PUT', 'PATCH'):
        try:
            body = await request.json()
        except Exception:
            body = None
        if isinstance(body, dict) and 'tenant_id' in body:
            supplied.append(body['tenant_id'])
    if any(value != company['tenant_id'] for value in supplied):
        raise denied()
    marker = context.set(company)
    try:
        yield company
    finally:
        context.reset(marker)


def provision(identifier, configuration):
    if not IDENTIFIER.fullmatch(identifier):
        raise HTTPException(422, 'Invalid request')
    secret = identifier + '.' + secrets.token_urlsafe(32)
    digest = hashlib.sha256(secret.encode('ascii')).hexdigest()
    rows = execute('''INSERT INTO companies (tenant_id, configuration, credential_digest)
        VALUES (%s, %s::jsonb, %s) ON CONFLICT (tenant_id) DO NOTHING RETURNING tenant_id''',
        (identifier, json.dumps(configuration.model_dump()), digest), write=True)
    if not rows:
        raise HTTPException(409, 'Company already provisioned')
    return {'tenant_id': identifier, 'credential': secret}


def configure(identifier, configuration):
    if not IDENTIFIER.fullmatch(identifier):
        raise HTTPException(422, 'Invalid request')
    rows = execute('UPDATE companies SET configuration=%s::jsonb WHERE tenant_id=%s RETURNING tenant_id',
                   (json.dumps(configuration.model_dump()), identifier), write=True)
    if not rows:
        raise HTTPException(404, 'Not found')
    return {'tenant_id': identifier, 'configuration': configuration.model_dump()}
