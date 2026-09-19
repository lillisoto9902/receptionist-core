# RECEPTIONIST CORE — PHASE 15 COMPLETION SNAPSHOT

## Product, review and Git baseline

CodeLogicAI LLC — Receptionist Core, Phase 15: production hardening,
deployment/reliability and controlled release-candidate validation.
Final Engineer Review completed September 19, 2026.
Live validation window: 2026-09-19 09:32:38 to 2026-09-19 09:45:43 EDT.

- Branch: `main`.
- Baseline HEAD: `8c7609240acdd0a28147a6fbf6684fbe716de2dd`.
- `HEAD...origin/main`: `0 0`, against the existing local tracking reference.
- Nothing staged. Phase 15 remains uncommitted; no commit, push or tag occurred.
- Before this snapshot: six modified tracked files and eight untracked files.
- The complete tracked diff and all untracked Phase 15 files were reviewed.
  All 51 baseline repository file hashes matched through live validation.
  This snapshot is the only review-stage addition. Production code, tests,
  dependencies, configuration and security behavior were not changed during review.

## Security hardening

Explicit environment, database target and administrator-token configuration fail
closed on missing, empty, malformed or inconsistent values. Local/test mode is
restricted to the approved isolated runtime target. Production TLS/configuration
requirements are documented; no production deployment was performed.

Administrator and tenant bearer scopes remain separate. Tenant credentials bind
to one company; constant-time verification, inactive-company rejection and
path/query/header/body ownership checks remain intact. Authenticated tenant
context scopes data access and scheduling. Malformed/duplicate auth inputs,
duplicate JSON fields, oversized requests and invalid model fields fail safely.

Operational logs retain fixed event categories, route templates, methods and
status codes. External errors are sanitized; credentials, verifiers, connection
URLs, SQL errors and customer payloads are not emitted. Public API documentation
endpoints are disabled. Bounded ingress is not claimed as shared rate limiting.

## Health, schema contract and M1 closure

Liveness remains independent of dependency availability. Readiness and application
lifespan startup validate operational configuration, database identity/privileges
and the current required application schema in a read-only transaction.

The schema contract covers all 19 initializer columns, their types and nullability,
required primary/unique keys, tenant foreign-key relationship, generated intake ID
sequence/default and creation-time default. It rejects incompatible tables,
missing/renamed columns and unsupported mandatory fields. No schema auto-repair,
startup DDL, migration framework or competing initializer was introduced.

An independent in-memory review probe reproduced the original M1 trigger by
renaming the required intake `name` column in disposable schema:

- Readiness returned 503 with `{"ready":false}`.
- Startup rejected the schema with a sanitized failure.
- A request against that incompatible schema returned a generic 503; readiness
  no longer incorrectly claimed that normal traffic could be served.
- The valid-schema control accepted startup, returned readiness 200 and created
  an authenticated scheduled intake through the actual application API.

Three automated live contract tests additionally cover every initializer column,
14 other incompatible-schema cases, deterministic restoration/teardown and
successful authenticated intake before and after restoration. M1 is closed.

## Reliability, scheduling and release-candidate workflow

Bounded connection, statement, lock and idle-transaction behavior is preserved.
An injected exception after PostgreSQL executed an INSERT but before commit left
no partial record; cleanup completed and a subsequent valid booking succeeded.
Database-unavailable responses remained sanitized and recovered after restoration.

Three synthetic companies with distinct credentials, configurations, hours,
services and timezones passed administrator provisioning, configuration/activation,
tenant authentication, intake, scheduling, persistence, retrieval and conflict
handling. Identical timestamps across tenants remained independent. Inactive
tenants, forged ownership and cross-tenant reads/writes were rejected.

Atomic company-row locking, full datetime/`scheduled_at TIMESTAMPTZ` persistence,
date-aware conflicts, timezone/local-midnight overlap protection, reservation
restoration and adjacent-slot handling passed. Application lifespan restart and
reconnection retained usable company configuration and tenant bindings; these
checks do not claim a separate production process-supervisor deployment.

The [operating contract](../setup/release-candidate-operations.md) documents
configuration, role separation, explicit migrator initialization, startup,
health/readiness, provisioning, recovery, rollback and graceful shutdown.
Backup/restore expectations use standard PostgreSQL tooling. Deterministic test
schema setup/cleanup was validated; an actual backup/restore drill was not performed.

## Fresh validation

| Targeted group | Passed |
|---|---:|
| Schema/readiness/startup contract | 3 |
| Request security and administrator authentication | 28 |
| Tenant isolation, provisioning and configuration | 26 |
| Scheduling, dates, timezone and concurrency | 47 |
| Configuration, reliability, health and readiness | 15 |
| Database guard | 16 |
| Live schema lifecycle, company workflow and release candidate | 3 |
| Complete regression, once after targeted validation | 138 |

Zero failures, errors or skips. Eight live integration tests are included across
the targeted groups and full suite. The independent M1 probe was additional
review evidence, not an added repository test. Validation used the approved
in-memory controller and existing explicit isolated-database opt-in.

## Database security and shutdown

- PostgreSQL 18.4; `receptionist_core_test`; port 55432; loopback listeners only;
  SCRAM-SHA-256. The unchanged public guard verified role, database, SQL identity,
  backend process, PID file, listener and authorized data directory.
- Administrator-only read-only preflight verified sensitive paths and HBA rules.
  Application workflows used the limited runtime role; setup used the migrator.
- Runtime CREATE/TEMP/ALTER denials passed. PUBLIC restrictions, role inventory,
  memberships, database privileges and default grants were preserved.
- No production/client data or port 5432 database connection was used.
  Credentials remained in process memory; files, ACLs and configuration were preserved.
- Scoped teardown restored zero application tables, records, relations, routines
  and types. Expected databases, roles and the public schema remained intact.
- Controlled shutdown returned zero. Isolated PID 7044 exited, port 55432
  closed, `postmaster.pid` was absent and control data reported clean shutdown.
- Port 5432 listeners/PID, the existing PostgreSQL service and service definitions
  remained unchanged. No Windows service was created or modified.

## Findings and accepted release gates

Critical: none. Major: none unresolved; M1 independently closed.
Minor: none identified within the approved scope. Blockers: none.

Each of the following remains INFORMATIONAL / RELEASE-GATE:

1. Shared/public rate limiting: requires approved and verified ingress/shared
   controls before public traffic; no fake in-memory production protection is claimed.
2. Dependency artifact approval: exact deployment artifacts and repeatability
   remain an operator approval gate; no dependency was added.
3. Witnessed restore drill: required before launch with agreed recovery/retention
   objectives; documentation and test schema recreation are not automated disaster recovery.
4. Historical undated-data conversion: requires separate review. Initialization
   refuses to invent dates; this does not block the supported clean-schema workflow.

These gates do not authorize public production deployment and are not unresolved
application defects in the reviewed controlled release candidate.

## Next action

Owner commit approval. No commit, push or tag occurred. Do not begin Phase 15.5
under this review authorization.

PHASE 15 FINAL ENGINEER REVIEW: PASS — READY FOR OWNER COMMIT APPROVAL

