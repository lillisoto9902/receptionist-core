# Phase 15 release-candidate operating contract

This contract covers controlled synthetic/local validation. It is not production
deployment authorization or evidence of an automated disaster-recovery system.
No new framework, dependency, identity provider or infrastructure is introduced.

## Required configuration and target

Provide configuration through a secret manager or protected process environment.
Do not place credentials in command lines, URLs sent to clients, reports or logs.
The existing internal `DATABASE_URL` is a secret and must never be logged.
The application does not read `.env`; only the explicit local launcher does.

| Variable | Requirement |
|---|---|
| RC_ENVIRONMENT | Explicit `local`, `test`, or `production`; no default |
| ADMIN_API_TOKEN | Securely generated 256-bit token, URL-safe ASCII, 43–128 characters; no placeholder |
| DATABASE_URL | PostgreSQL URL with credentials and explicit port; target must match all declarations below |
| RC_DATABASE_HOST / RC_DATABASE_PORT | Explicit approved target |
| RC_DATABASE_NAME / RC_DATABASE_USER | Explicit database and least-privilege runtime role |

Local/test modes accept only `127.0.0.1:55432/receptionist_core_test` as
`receptionist_core_test_app`. The existing isolated environment uses SCRAM and
loopback, with TLS disabled only on this local connection. Inherited `PG*` variables
and URL overrides other than `sslmode`/`sslrootcert` are rejected.

Production mode requires a non-local, non-test database target, `sslmode=verify-full`
and an explicit absolute existing `sslrootcert` path. Production credentials and
infrastructure are not supplied or exercised by Phase 15. PostgreSQL 18.4 or a
later PostgreSQL 18 maintenance release is the operational database contract.

## Startup, schema and ownership

1. Complete the deployment gates below; provision the approved database and separate
   migrator/runtime roles through an independently authorized operator procedure.
2. Runtime needs CONNECT, public-schema USAGE, company SELECT/INSERT/UPDATE, intake
   SELECT/INSERT/UPDATE/DELETE, and intake sequence USAGE. It must not own schema
   objects or have database/schema CREATE, TEMP, elevated flags or role memberships.
   Keep PUBLIC restrictions. The migrator owns schema objects and default grants.
3. Initialize through the existing `app.main.init_db(connection_factory=...)`,
   supplying an operator-approved migrator connection factory. Runtime startup
   performs no DDL and refuses a missing/incompatible schema. The isolated harness
   supplies its unchanged guarded migrator; never substitute a runtime superuser.
   Do not run initialization over undated legacy records or invent dates.
4. Inject operational configuration and validate it with `load_settings()` before
   starting the service. Do not use Python optimization flags as a configuration
   bypass; validation remains active under them.
5. Start Uvicorn with lifespan enabled, access logging disabled and proxy headers
   disabled unless a separately reviewed trusted-proxy configuration replaces it.
   Example executable/arguments: `uvicorn app.main:app --host 127.0.0.1 --port 8000
   --lifespan on --no-access-log --no-proxy-headers`. Inject secrets separately.
   The local launcher enables reload and must not be used for production.
6. Confirm `/health` returns 200 (liveness), and `/ready` returns 200 with
   `{"ready":true}`. Readiness checks configuration, database identity/least privilege,
   schema columns and permissions. Failure returns only `{"ready":false}` with 503.
7. Use the platform bearer to provision/activate a company, securely capture its
   one-time tenant credential, then validate tenant-scoped intake and retrieval.

Startup fails with a generic message if configuration, dependency or schema validation
fails. API documentation endpoints are disabled. The database connector uses bounded
connection/statement/lock/idle-transaction timeouts and READ COMMITTED isolation.
Booking checks and writes remain under one tenant-row lock and transaction.

## Request and log policy

The ASGI boundary caps body bytes at 64 KiB, headers at 16 KiB, path/query length at
2048 each, and body receipt at five seconds. Duplicate JSON keys, ambiguous auth,
duplicate tenant headers/query IDs and malformed JSON are rejected. Fields and
configuration remain validated with the current Pydantic models. These bounds are
not request-rate protection and do not replace edge controls.

The `receptionist.operations` logger emits only fixed event categories, HTTP method,
route templates and status. Enable its INFO level with the operator's standard logging
configuration. Do not enable request-body/header dumps, raw query-string access logs,
driver debug output or exception-local-variable capture. Tenant/admin credentials,
verifiers and customer data must be excluded from ingress/APM logs too. Readiness
responses disclose no target, credentials, tenant data or exception details.

## Release gates before public traffic

- **Rate/abuse protection is an unresolved deployment dependency.** There is no shared
  rate limiter in this architecture. Before public launch, the Owner/operator must
  select and validate trusted ingress/shared throttling for authentication,
  provisioning, intake and readiness, plus connection/body/time limits. Do not expose
  this candidate directly to hostile public traffic. No in-memory limiter is claimed.
- Configure and verify HTTPS ingress, network access controls, process supervision,
  secret injection, log retention/redaction and graceful shutdown. Proxy trust must
  be explicit; never trust arbitrary forwarded client headers.
- Approve exact dependency artifacts and a repeatable environment using the existing
  requirements; the current dependency list is not a locked deployment image.
- Demonstrate restore recovery and agree backup retention, RPO/RTO and monitoring.
  Public deployment requires separate authorization. Controlled local RC validation
  may proceed while these operator gates remain open.

## Failure recovery and shutdown

On an expected database fault, return generic 503, roll back/close connections, and
allow the next request to recover after dependency restoration. Do not blindly retry
write requests after a lost response: a disconnect during commit can leave the caller
uncertain whether the write committed. Reconcile persisted records before resubmission.
Liveness may remain 200 during a dependency outage; readiness must become 503.

Stop accepting traffic, drain in-flight requests, and stop Uvicorn through its normal
graceful shutdown. No application-owned connection pool survives shutdown. Restart
performs readiness validation again against persisted configuration/schema. Roll back
application artifacts only to a schema-compatible reviewed release; do not automatically
reverse schema changes or erase records. Never run test teardown on a deployed database.

## Backup and restore expectations

Use standard PostgreSQL 18 `pg_dump` custom-format backups and `pg_restore` for an
operator-approved separate recovery database. Supply credentials using protected
credential storage, never inline command arguments. Encrypt/restrict backup files:
they contain tenant verifiers and customer records. Backup configuration/HBA/role/grant
definitions separately under restricted access; database dumps alone are not sufficient.

Validate archive integrity, restore into an isolated approved target, re-establish the
least-privilege roles/default grants, verify schema/row counts and application readiness,
and exercise authenticated synthetic workflows. Do not use destructive restore flags
against an existing service or connect test tooling to port 5432. No automatic restore
script is provided. Backup scheduling, storage, retention and disaster recovery are
operator responsibilities requiring a witnessed restore drill before launch.

The RC tests prove deterministic schema initialization, synthetic population, scoped
cleanup/recreation, transaction rollback and application restart/reconnect persistence.
They do not constitute a `pg_dump`/`pg_restore` or infrastructure disaster-recovery drill.
