"""Exclusive, empty-database test lifecycle using the application's existing DDL.

Never starts a server, loads .env, grants privileges, or runs application startup.
The caller must complete administrator/OS preflight and own cluster shutdown.
"""

import io
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from unittest.mock import patch

from app import main
from . import _database_guard as guard


class BorrowedConnection:
    """Keep the real transaction and connection under harness ownership."""

    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return self.connection.cursor()

    def commit(self):
        pass

    def rollback(self):
        self.connection.rollback()

    def close(self):
        pass


def relations(connection):
    return guard.query(connection, """
        SELECT n.nspname,c.relname,c.relkind,pg_get_userbyid(c.relowner)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
        ORDER BY 1,2
    """)


def bootstrap(connection):
    """Reuse init_db, but suppress its raw error output and implicit commit."""
    output = io.StringIO()
    with redirect_stdout(output), redirect_stderr(output), patch.object(
        main, 'get_db_connection', return_value=BorrowedConnection(connection)
    ):
        main.init_db()
    guard.require(not output.getvalue(), 'Schema bootstrap failed')
    expected = [
        ('public', 'companies', 'r', guard.MIGRATOR_ROLE),
        ('public', 'companies_credential_digest_key', 'i', guard.MIGRATOR_ROLE),
        ('public', 'companies_pkey', 'i', guard.MIGRATOR_ROLE),
        ('public', 'intake_requests', 'r', guard.MIGRATOR_ROLE),
        ('public', 'intake_requests_id_seq', 'S', guard.MIGRATOR_ROLE),
        ('public', 'intake_requests_pkey', 'i', guard.MIGRATOR_ROLE),
        ('public', 'intake_requests_tenant_idx', 'i', guard.MIGRATOR_ROLE),
    ]
    guard.require(relations(connection) == expected, 'Unexpected schema inventory')


@contextmanager
def isolated_schema(target):
    """Commit approved DDL, yield, then drop only this run's new table.

    Requires exclusive use and an empty application-object inventory. Runtime
    transactions must be rolled back and closed before leaving this context.
    DROP has no CASCADE; PostgreSQL removes the owned serial sequence and index.
    A failed cleanup is an explicit failure, never a reason to drop other objects.
    """
    connection = target.connect(guard.MIGRATOR_ROLE)
    created = False
    try:
        guard.query(connection, "SET statement_timeout = '5s'")
        guard.query(connection, "SET lock_timeout = '2s'")
        guard.query(connection, 'SET search_path = public')
        guard.require(not relations(connection), 'Setup requires empty database')
        guard.require(not guard.query(connection, """
            SELECT 1 FROM pg_namespace WHERE nspname !~ '^pg_'
            AND nspname NOT IN ('public','information_schema')
            UNION ALL
            SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
            UNION ALL
            SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
            WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
        """), 'Setup requires empty application objects')
        bootstrap(connection)
        bootstrap(connection)  # Existing initializer is repeatable before commit.
        connection.commit()
        created = True
        yield
    except Exception:
        raise guard.SafetyError('Schema integration lifecycle failed') from None
    finally:
        try:
            connection.rollback()
            if created:
                expected_names = {'companies','companies_pkey','companies_credential_digest_key','intake_requests','intake_requests_id_seq','intake_requests_pkey','intake_requests_tenant_idx'}
                inventory = relations(connection)
                guard.require(len(inventory) == 7 and all(
                    row[0] == 'public' and row[1] in expected_names
                    and row[3] == guard.MIGRATOR_ROLE for row in inventory
                ), 'Cleanup inventory mismatch')
                guard.query(connection, 'DROP TABLE public.intake_requests')
                guard.query(connection, 'DROP TABLE public.companies')
                guard.require(not relations(connection), 'Cleanup left application relations')
                connection.commit()
        except Exception:
            connection.rollback()
            raise guard.SafetyError('Schema cleanup failed; safe follow-up required') from None
        finally:
            connection.close()
