# Receptionist Core release-candidate checklist

This is an implementation/operations checklist, not a Phase 15 completion snapshot.
Follow [the operating contract](release-candidate-operations.md).

- Verify explicit environment, target declarations, strong admin credential and protected
  database configuration. No secrets in artifacts, logs or command lines.
- Confirm migrator-owned schema, limited runtime role, PUBLIC restrictions and no runtime
  CREATE/TEMP/ALTER capability. Do not use runtime schema initialization.
- Verify startup fails on missing/invalid configuration, unsafe target or schema;
  `/health` is liveness and `/ready` checks dependency/schema readiness safely.
- Validate three distinct synthetic companies through actual provisioning,
  configuration/activation, authentication, intake, scheduling, persistence and retrieval.
- Recheck tenant mismatches, cross-tenant access, inactive tenants, duplicate provisioning,
  malformed requests, bounded bodies and sanitized errors/logs.
- Recheck concurrency, date preservation, timezone-change overlap, adjacent intervals,
  different dates and independent tenant bookings.
- Exercise an insert failure before commit, verify rollback/no partial row, then recover
  on a valid request. Reconnect/restart without losing persisted configuration.
- Run targeted groups, then the complete suite once. Preserve the isolated database
  guard and verify mandatory cleanup/shutdown with port 5432 unchanged.
- Obtain independent Engineer Review before Phase 15 completion/Git closure.

## Separate public-launch gates

Do not expose this candidate publicly until the Owner/operator has approved and verified
shared ingress rate/abuse controls, HTTPS/network boundaries, secret and log management,
supervision, exact dependency artifacts, and a witnessed backup/restore drill with
retention and recovery objectives. No production deployment, external infrastructure,
rate limiter, or automatic disaster-recovery capability is supplied or certified by
these local implementation tests.
