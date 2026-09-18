# Isolated integration setup contract

The existing `app.main.init_db()` raw SQL is the schema authority. There is no
ORM or migration framework. This harness adds no dependency and does not change
production startup. Future schema changes require review of that initializer and
this contract together; this is not production migration automation.

Before opting in, the operator must exclusively reserve the isolated database,
verify the stopped PostgreSQL 18.4 cluster, exact data/config/HBA paths, restricted
credential ACLs, unused port 55432, and record the separate port 5432/service state.
Use the previously approved bounded `pg_ctl` startup against
`C:\Users\sotoa\AppData\Local\CodeLogicAI\ReceptionistCore\Postgres18Test\data`.
Administrator-only preflight must verify the cluster identity, paths, loopback
listeners, SCRAM HBA, database/role inventory and established PUBLIC/default grants.
The administrator is never used to create test objects or execute the application.

Remove inherited PG-prefixed variables from the runner process and set
`RUN_RECEPTIONIST_DB_INTEGRATION=1` only for the approved live run. The unchanged
`Target` guard reads fixed protected credentials in memory and validates every
connection: receptionist_core_test, 127.0.0.1:55432, PostgreSQL 18.4, expected role,
PID file, listener, backend parent and executable. Never load the regular `.env`,
log credentials, bypass the guard, or use application lifespan startup.

Focused invocation from the repository root:

```powershell
python -B -m unittest discover -s tests -p test_schema_setup.py -v
```

Without the opt-in, the live test is skipped. Opt-in alone does not replace the
operator preflight. The harness never starts/stops the server or changes grants.

`isolated_schema` requires no application objects and uses only the migrator.
It reuses the existing initializer twice inside a harness-owned transaction,
suppresses its raw error output, verifies the resulting inventory, then commits
the table `public.intake_requests`, its serial sequence and primary-key index.
The application role uses only the established table CRUD and sequence grants.
It receives no ownership, CREATE, TEMP, membership or elevated role capability.

Runtime validation uses synthetic rows with transaction rollback. It exercises
the current scheduling read path, CRUD, and denied CREATE/TEMP/ALTER. No fixture
is committed. After closing runtime connections, teardown uses the same migrator
to drop only the newly created table without CASCADE, removing its owned sequence
and index. It refuses unexpected inventories and never clears an existing schema.
The expected final database is empty again. This lifecycle requires exclusive use;
it is not a parallel-test harness. A failed cleanup requires safe follow-up, not
broad cleanup or another run. An interrupted controller may leave the committed
test schema; do not retry until reviewed.

Run focused tests, then the full `python -B -m unittest discover -s tests -v`
suite once with the approved live opt-in. Compare database, role, privilege,
configuration and service state afterward. Always stop the isolated cluster with
bounded `pg_ctl stop -m fast -w`, including on failure, and verify closed 55432,
exited server PID, absent postmaster.pid and clean control-data shutdown. Preserve
credentials and port 5432. No production or client database is in scope.
