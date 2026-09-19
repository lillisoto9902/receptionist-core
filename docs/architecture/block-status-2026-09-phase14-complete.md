# RECEPTIONIST CORE — PHASE 14 COMPLETION SNAPSHOT

## Product, review and Git baseline

Receptionist Core — Phase 14: customerization and the company/tenant foundation.
Final Engineer Review completed September 19, 2026. Live validation ran on
September 18 from 15:59:47 to 16:14:34 EDT; completion resumed September 19.

- Branch: `main`.
- Baseline HEAD: `a16ae816e7d2e609ae725b1962654c335ecf7947`.
- `HEAD...origin/main`: `0 0`, against the existing local tracking reference.
- Nothing staged. Phase 14 remains uncommitted; no commit, push or tag occurred.
- Before this snapshot: six modified tracked files and nine untracked files.
- The complete tracked diff and all untracked Phase 14 files were reviewed.
  All 42 baseline file hashes matched through validation and on resumption.
  This snapshot is the only Engineer Review-stage addition; no production code,
  tests, dependencies, configuration or security behavior changed during review.

## Approved foundation and authenticated workflow

- PostgreSQL stores company configuration and the company-bound credential verifier.
  Ordinary provisioning/configuration requires no source-code edit.
- Administrator-only provisioning uses the existing platform bearer boundary.
  Generated tenant credentials bind to exactly one canonical company. Only the
  SHA-256 verifier of the high-entropy secret is stored; verification uses
  `secrets.compare_digest`. The generated secret is returned once at provisioning.
- Administrator credentials are not a tenant fallback. Tenant credentials cannot
  provision companies. Path, body, query and header tenant-ID mismatches fail closed.
- Authenticated tenant context controls intake ownership, reads, updates, deletes,
  configuration and scheduling. Isolation is enforced by application queries;
  direct database credentials remain trusted server credentials, not tenant access.
- Duplicate provisioning preserves the existing credential. Activation/deactivation
  works, inactive tenants are rejected, and configuration persists across reconnects.
  Hours, services, durations, timezone and interval settings are validated.
- Real authenticated provisioning, intake, availability, record access and status
  workflows passed, including cross-tenant and forged-ownership rejection.

## All three prior Major findings closed

1. **Concurrent booking:** the authenticated company's row is locked before the
   authoritative availability recheck and insert on the same connection/transaction.
   Two synchronized real requests for one tenant/date/slot produced one committed
   booking and one sanitized rejection; persisted count was exactly one. Rejection
   left no partial booking. Reservation restoration uses the same lock and conflict
   check. Different companies use separate locks; connection cleanup passed.
2. **Date preservation:** required `scheduled_at TIMESTAMPTZ` preserves the instant;
   the existing textual fields retain full datetime and offset. Read-back reconstructed
   the accepted appointment. Same-tenant January 3 and January 4 bookings at 09:00
   remained independently bookable. Malformed dates fail safely.
3. **Timezone/local-midnight overlap:** conflict lookup includes all reserving
   appointments for the authenticated tenant. UTC interval comparison implements
   `requested_start < existing_end AND existing_start < requested_end`.
   A 60-minute booking at `2030-01-03T04:30:00Z`, followed by a UTC-to-New-York
   configuration change, blocked `2030-01-03T00:00:00-05:00`. The original timestamp
   was unchanged, rejection was sanitized, and persisted count remained one.

True overlaps, including across local midnight, are rejected. Adjacent and separate
intervals, non-overlapping dates, and equivalent intervals for different tenants
remain bookable. Local business hours and grid validation remain enforced. Historical
timestamps are not rewritten when configuration changes. No global lock, external
locking service, new dependency, authentication redesign or calendar redesign was added.

## Fresh validation results

| Targeted validation | Result |
|---|---|
| Date unit tests | 6 passed |
| Timezone/interval unit tests | 6 passed |
| Live concurrency/date regression | 1 passed |
| Live timezone-change regression | 1 passed |
| Scheduling unit/API tests | 33 passed |
| Company authentication/isolation | 15 passed |
| Provisioning/configuration | 11 passed |
| Database guard | 16 passed |
| Live schema lifecycle | 1 passed |
| Live authenticated company workflow | 1 passed |
| Complete regression, once after targeted tests | 104 passed |

There were zero failures, errors or skips. Four live integration tests are included
in the targeted rows above and in the full suite. Tests ran through an in-memory
`python -B -` controller with the existing explicit isolated-database opt-in.
No test assertion or production implementation was changed during review.

## Database security and final shutdown

- PostgreSQL 18.4; database `receptionist_core_test`; port 55432; loopback listeners
  `127.0.0.1` and `::1`; SCRAM-SHA-256. Unchanged public guard checks validated
  connection target, role, SQL identity and backend/PID/listener/data-directory identity.
- Administrator-only read-only preflight verified sensitive paths and HBA rules.
  Application execution used the limited runtime role; schema setup used the migrator.
- Runtime CREATE, TEMP and ALTER denials passed. PUBLIC restrictions, role inventory,
  memberships, privileges and default grants remained unchanged. No privilege expansion.
- No plaintext credentials were persisted or disclosed. Credential files/ACLs and
  PostgreSQL configuration remained preserved. No production/client data was accessed.
- Scoped teardown restored zero application tables, records, relations, routines and
  types. The expected public schema and database/role inventories remained intact.
- Bounded controlled shutdown returned zero. Isolated PID 6756 exited; port 55432
  closed; `postmaster.pid` was absent; control data reported `shut down`.
- Port 5432 listeners/PID, existing PostgreSQL service and service definitions were
  preserved during the run. No connection was made to port 5432 and no service changed.
- Read-only checks on September 19 reconfirmed the isolated cluster was stopped,
  port 55432 absent, and the existing PostgreSQL service running with port 5432 available.

## Findings and accepted limitation

- Critical: none.
- Major: none unresolved; all three prior findings independently closed.
- Minor: none identified within the approved Phase 14 scope.
- Informational: existing undated records require separately reviewed conversion.
  Initialization refuses to invent dates. Supported clean provisioning requires
  `scheduled_at`, and current booking workflows always supply it. No legacy migration
  was performed; supported clean deployments are unaffected by this limitation.
- Blockers: none. The implementation remains within approved Phase 14 scope.

## Next action

Owner commit approval. No commit, push or tag has occurred. Do not begin Phase 15
under this review authorization.

PHASE 14 FINAL ENGINEER REVIEW: PASS — READY FOR OWNER COMMIT APPROVAL
