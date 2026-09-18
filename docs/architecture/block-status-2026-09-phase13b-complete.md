# RECEPTIONIST CORE — PHASE 13B COMPLETION SNAPSHOT

## Product and phase

Receptionist Core — Phase 13B: scheduling safety and isolated integration setup.

Completion review: September 18, 2026. Live validation ran from 06:13:34 to
06:14:18 EDT. Implementation remains uncommitted pending Owner approval.

## Git baseline and working state

- Branch: `main`
- HEAD: `53cf8a5fdf6276f4b56ab989d267b355e1d28c8c`
- `HEAD...origin/main`: `0 0`, against the existing local tracking reference.
- Nothing staged; no commit, push, dependency change, or deployment occurred.
- Modified before review: `app/main.py`.
- Untracked before review: `tests/integration/__init__.py`,
  `tests/integration/_database_guard.py`, `tests/integration/_schema_setup.py`,
  `tests/integration/test_schema_setup.py`, `tests/test_database_guard.py`,
  `tests/test_scheduling_api.py`, `tests/test_scheduling_unit.py`, and
  `docs/setup/isolated-integration.md`.
- This snapshot is the only file added or changed during Engineer Review.

## Approved scope completed

- Scheduling lookup failures and malformed reserving bookings fail closed.
  Booking rows require valid time components and positive integer durations.
- Scheduling errors propagate to generic HTTP 503 responses without partial
  availability results or an intake insert after a failed availability lookup.
- Admission enforces opening at 09:00, the 30-minute grid, and completion by 17:00.
  Existing duration, overlap, lead-time and advance-window behavior is covered.
- Scheduling lookup cursors and connections close on success and failure.
- Connection logging omits raw driver errors. Existing bearer authentication,
  generic failures and `secrets.compare_digest()` behavior remain unchanged.
- Standard-library unittest coverage includes scheduling unit/API behavior,
  database-guard rejection paths, and the live schema lifecycle.

## Isolated database and security controls

The approved environment is PostgreSQL 18.4, database `receptionist_core_test`,
port 55432, listeners `127.0.0.1` and `::1`, with SCRAM-SHA-256 HBA rules.
The authorized data directory is
`C:\Users\sotoa\AppData\Local\CodeLogicAI\ReceptionistCore\Postgres18Test\data`.

The unchanged guard requires explicit opt-in, fixed protected credential files,
the exact database, IPv4 connection address, port and expected limited role. It
rejects inherited PG-prefixed environment settings and URL overrides, validates
PostgreSQL 18.4 and binds the SQL backend to the authorized PID file, listener,
parent process and PostgreSQL executable. `host(inet_server_addr())` returns
exactly `127.0.0.1`; the connection omits the defective `service=""` argument.
Credential/configuration, target, authentication, SQL identity and OS identity
failures remain sanitized. No credentials or complete connection URL were emitted.

Administrator-only read-only preflight verified sensitive configuration/data/HBA
paths and SCRAM rules. Role inventory used explicit non-secret `pg_roles` columns;
no password verifier was queried. The previously approved exception permits only
the guard's existing identity SELECT in autocommit. Preflight/postflight catalog
validation used verified read-only transactions followed by rollback.

`receptionist_core_test_migrator` owns setup objects and retains its previously
approved test-database privileges. `receptionist_core_test_app` has runtime table
CRUD and sequence USAGE/SELECT through existing default grants, without grant
options. Neither limited role has superuser, role/database creation, replication,
bypass-RLS, or role memberships. Runtime database CREATE/TEMP and public-schema
CREATE remain denied. Live CREATE, TEMP-table creation and ALTER attempts returned
insufficient privilege. PUBLIC restrictions and role/privilege metadata remained
unchanged. No privileges, services, credentials or configuration were modified.

## Schema and integration setup

The existing raw-SQL `app.main.init_db()` remains the schema authority. The harness
borrows a guarded migrator connection, controls commit/close, captures the legacy
initializer's raw output, and verifies initialization twice before commit. No ORM,
migration library, duplicate DDL definition or new dependency was introduced.

Setup requires an empty application-object inventory. It creates only the existing
application's `public.intake_requests`, owned serial sequence and primary-key
index. Runtime validation authenticates independently as the application role,
checks the schema, exercises CRUD and real scheduling reads with minimal synthetic
rows, and rolls back runtime transactions. Teardown closes runtime connections and
drops only this run's table without CASCADE, removing its owned sequence/index.
Application startup/lifespan is not executed. No fixture or client record persists.

## Independent Engineer Review and validation

The complete tracked diff and all untracked Phase 13B files were reviewed for
security, scheduling, schema ownership, cleanup, secret handling and scope.
No production-code or test edits were made during review. No speculative entities,
production automation, authentication redesign or later-phase features were added.

| Validation | Result |
|---|---|
| Database-guard targeted tests | 16 passed |
| Scheduling unit/API targeted tests | 33 passed |
| Live schema/integration targeted test | 1 passed |
| Full regression suite, once after targeted validation | 63 passed |
| Failures / errors / skips | 0 / 0 / 0 |
| Both limited-role live identity guards | PASS |
| Complete diff and whitespace review | PASS; existing LF/CRLF warning only |
| Repository preservation during validation | All 32 baseline file hashes matched |

Tests used unittest discovery with patterns `test_database_guard.py`,
`test_scheduling_*.py`, `test_schema_setup.py`, then `test*.py`, in an in-memory
`python -B -` runner. The live opt-in was enabled for the approved run. The full
suite includes the live lifecycle again and 13 existing authentication tests.

## Final database state and mandatory shutdown

- Cleanup restored the original application-object inventory: zero application
  tables, relations, routines, types and records; expected public schema retained.
- Database inventory, roles, memberships, privileges and default grants matched.
- Configuration-file hashes, credential metadata/ACLs and cluster resources were
  preserved. No production/client database or data was accessed.
- Isolated server PID 16700 exited; bounded `pg_ctl stop -m fast` returned 0.
- Port 55432 closed; `postmaster.pid` absent; control data reported `shut down`.
- Port 5432 listeners/PID, existing PostgreSQL service and Windows service
  definitions remained unchanged. No connection was made to port 5432.

## Findings and accepted limitations

- Critical: none.
- Major: none.
- Minor: none identified within this Phase 13B scope.
- Informational: exclusive database use and operator preflight/shutdown are required.
  A terminated controller can leave committed test schema. This is acceptable for
  the controlled isolated environment: subsequent setup refuses existing objects,
  and documentation requires reviewed recovery instead of broad cleanup or retry.
- Informational: the integration test covers schema lifecycle, runtime CRUD and
  scheduling reads; it is not a production deployment or concurrent-booking test.
  Existing calendar-date, concurrency and tenant-architecture limitations are not
  resolved or certified by this phase.

## Next action

Owner review and local commit authorization. No commit or push has yet occurred.
Do not begin later-phase work under this review authorization.

PHASE 13B ENGINEER REVIEW: PASS — READY FOR OWNER COMMIT APPROVAL
