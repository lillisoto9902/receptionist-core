"""Fail-closed operational configuration and bounded database acquisition."""
import os
import re
import logging
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

import psycopg2


class ConfigurationError(RuntimeError):
    pass


class DatabaseUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    mode: str
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)
    sslmode: str = 'disable'
    rootcert: str = ''


def require(condition):
    if not condition:
        raise ValueError()


def load_settings():
    try:
        mode = os.environ['RC_ENVIRONMENT']
        require(mode in ('test', 'local', 'production'))
        token = os.environ['ADMIN_API_TOKEN']
        require(re.fullmatch(r'[A-Za-z0-9_-]{43,128}', token) and len(set(token)) >= 10)
        require(not any(k.upper().startswith('PG') for k in os.environ))
        raw = os.environ['DATABASE_URL']
        require(raw == raw.strip() and not any(ord(c) < 33 for c in raw))
        url = urlsplit(raw)
        require(url.scheme == 'postgresql' and not url.fragment)
        host, port = os.environ['RC_DATABASE_HOST'], int(os.environ['RC_DATABASE_PORT'])
        database, user = os.environ['RC_DATABASE_NAME'], os.environ['RC_DATABASE_USER']
        require(re.fullmatch(r'[A-Za-z0-9_.-]{1,253}', host))
        require(all(re.fullmatch(r'[a-z][a-z0-9_]{0,62}', x) for x in (database, user)))
        require(1 <= port <= 65535 and url.hostname == host and url.port == port)
        require(url.path == '/' + database and unquote(url.username or '') == user)
        password = unquote(url.password or '')
        require(len(password) >= 20 and len(set(password)) >= 8 and all(ord(c) >= 32 for c in password))
        pairs = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
        options = dict(pairs)
        require(len(options) == len(pairs) and set(options) <= {'sslmode', 'sslrootcert'})
        if mode in ('test', 'local'):
            require((host, port, database, user) == ('127.0.0.1', 55432, 'receptionist_core_test', 'receptionist_core_test_app'))
            require(options.get('sslmode', 'disable') == 'disable' and 'sslrootcert' not in options)
        else:
            require(host not in ('localhost', '127.0.0.1', '0.0.0.0') and database != 'receptionist_core_test')
            require(options.get('sslmode') == 'verify-full')
            cert = Path(options['sslrootcert'])
            require(cert.is_absolute() and cert.is_file())
        return Settings(mode, host, port, database, user, password,
                        options.get('sslmode', 'disable'), options.get('sslrootcert', ''))
    except Exception:
        raise ConfigurationError('Operational configuration invalid') from None


def validate_connection(connection, settings):
    """Identity and least privilege; no sensitive settings or credential catalogs."""
    with connection.cursor() as cursor:
        cursor.execute('''SELECT current_database(),current_user,
            current_setting('server_version_num')::int,
            rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls,
            has_database_privilege(current_user,current_database(),'CREATE'),
            has_database_privilege(current_user,current_database(),'TEMP'),
            has_schema_privilege(current_user,'public','CREATE'),
            EXISTS(SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid)
            FROM pg_roles WHERE rolname=current_user''')
        row = cursor.fetchone()
        if not row or row[:2] != (settings.database, settings.user) or not 180004 <= row[2] < 190000 or any(row[3:]):
            raise DatabaseUnavailable('Database unavailable')


def connect():
    settings = load_settings()
    connection = None
    stage = 'connection'
    try:
        kwargs = dict(host=settings.host, port=settings.port, dbname=settings.database,
                      user=settings.user, password=settings.password, sslmode=settings.sslmode,
                      connect_timeout=5, application_name='receptionist_core',
                      options='-c statement_timeout=5000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=15000 -c search_path=public,pg_catalog')
        if settings.rootcert:
            kwargs['sslrootcert'] = settings.rootcert
        connection = psycopg2.connect(**kwargs)
        connection.set_session(isolation_level='READ COMMITTED')
        stage = 'identity'
        validate_connection(connection, settings)
        connection.rollback()
        return connection
    except Exception:
        if connection is not None:
            connection.close()
        logging.getLogger('receptionist.operations').warning('database_unavailable stage=%s', stage)
        raise DatabaseUnavailable('Database unavailable') from None


# Minimum current runtime contract, checked against init_db by live drift tests.
# This is validation metadata, not a second initializer or migration definition.
REQUIRED_COLUMNS = {
    'companies': {
        'tenant_id': ('text', True), 'configuration': ('jsonb', True),
        'credential_digest': ('text', True),
    },
    'intake_requests': {
        'id': ('integer', True), 'tenant_id': ('text', True),
        'scheduled_at': ('timestamp with time zone', True),
        'name': ('text', True), 'phone': ('text', True),
        'email': ('text', False), 'reason': ('text', True),
        'preferred_time': ('text', False), 'source': ('text', False),
        'scheduled_time': ('text', False), 'appointment_status': ('text', True),
        'service_type': ('text', False), 'industry': ('text', False),
        'duration_minutes': ('integer', False), 'priority': ('text', False),
        'created_at': ('timestamp without time zone', False),
    },
}


def validate_schema(cursor):
    """Inspect only public catalog metadata; never repair schema or read rows."""
    cursor.execute('''SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),
        a.attnotnull,c.relkind,a.atthasdef,a.attgenerated,a.attidentity
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_attribute a ON a.attrelid=c.oid
        WHERE n.nspname='public' AND c.relname IN ('companies','intake_requests')
        AND a.attnum>0 AND NOT a.attisdropped''')
    columns = {}
    for table, column, kind, required, relation, has_default, generated, identity in cursor.fetchall():
        if column not in REQUIRED_COLUMNS[table] and required and not (has_default or generated or identity):
            # Runtime INSERTs cannot supply an unknown mandatory field.
            raise DatabaseUnavailable('Database unavailable')
        columns[table, column] = (kind, required, relation, generated, identity)
    for table, expected in REQUIRED_COLUMNS.items():
        for column, (kind, required) in expected.items():
            actual = columns.get((table, column))
            if actual != (kind, required, 'r', '', ''):
                raise DatabaseUnavailable('Database unavailable')

    cursor.execute('''SELECT c.relname,k.contype,
        ARRAY(SELECT a.attname::text FROM unnest(k.conkey) WITH ORDINALITY x(num,pos)
              JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=x.num ORDER BY x.pos),
        rn.nspname,rc.relname,
        ARRAY(SELECT a.attname::text FROM unnest(k.confkey) WITH ORDINALITY x(num,pos)
              JOIN pg_attribute a ON a.attrelid=k.confrelid AND a.attnum=x.num ORDER BY x.pos),
        k.convalidated,k.condeferrable
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_class rc ON rc.oid=k.confrelid
        LEFT JOIN pg_namespace rn ON rn.oid=rc.relnamespace
        WHERE n.nspname='public' AND c.relname IN ('companies','intake_requests')
        AND k.contype IN ('p','u','f')''')
    constraints = {(table, kind, tuple(keys), schema, referenced, tuple(foreign))
                   for table, kind, keys, schema, referenced, foreign, valid, deferred
                   in cursor.fetchall() if valid and not deferred}
    required_constraints = {
        ('companies', 'p', ('tenant_id',), None, None, ()),
        ('companies', 'u', ('credential_digest',), None, None, ()),
        ('intake_requests', 'p', ('id',), None, None, ()),
        ('intake_requests', 'f', ('tenant_id',), 'public', 'companies', ('tenant_id',)),
    }
    if not required_constraints <= constraints:
        raise DatabaseUnavailable('Database unavailable')

    cursor.execute('''SELECT a.attname,pg_get_expr(d.adbin,d.adrelid)
        FROM pg_attribute a JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        WHERE a.attrelid='public.intake_requests'::regclass
        AND a.attname IN ('id','created_at')''')
    defaults = dict(cursor.fetchall())
    cursor.execute("SELECT pg_get_serial_sequence('public.intake_requests','id'), 'public.intake_requests_id_seq'::regclass::text")
    owned_sequence, sequence_name = cursor.fetchone()
    if (owned_sequence != 'public.intake_requests_id_seq'
            or defaults.get('id') != "nextval('" + sequence_name + "'::regclass)"
            or defaults.get('created_at') != 'CURRENT_TIMESTAMP'):
        raise DatabaseUnavailable('Database unavailable')


def check_ready(connection_factory):
    settings = load_settings()
    with closing(connection_factory()) as connection:
        try:
            connection.set_session(readonly=True)
            validate_connection(connection, settings)
            with connection.cursor() as cursor:
                validate_schema(cursor)
                cursor.execute("SELECT (SELECT bool_and(has_table_privilege(current_user,'companies',p)) FROM unnest(ARRAY['SELECT','INSERT','UPDATE']) p), (SELECT bool_and(has_table_privilege(current_user,'intake_requests',p)) FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) p), has_sequence_privilege(current_user,'intake_requests_id_seq','USAGE')")
                if not all(cursor.fetchone()):
                    raise DatabaseUnavailable('Database unavailable')
        finally:
            connection.rollback()
