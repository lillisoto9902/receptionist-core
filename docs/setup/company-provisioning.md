# Company provisioning and tenant boundary

Phase 14 extends the existing bearer-token pattern. No identity provider, user
system, ORM or dependency is added. PostgreSQL is authoritative for company
configuration and tenant credential association; no process cache is used.

| Endpoint | Boundary |
|---|---|
| POST /platform/companies/{tenant_id} | Existing platform administrator bearer |
| PUT /platform/companies/{tenant_id} | Platform administrator; includes activation/deactivation |
| GET/PUT /companies/{tenant_id} | Tenant bearer, exact authenticated company only |
| /settings, /dashboard/stats, /intakes and all record/filter/status routes | Tenant bearer |
| POST /intake, POST /availability | Tenant bearer |
| /, /health, /admin/dashboard/demo | Existing public non-customer content |

The administrator token is not a tenant fallback. Tenant tokens cannot provision
companies. A request's canonical company is resolved from its verified bearer,
never from an untrusted ID. Path/body/query `tenant_id` and `X-Tenant-ID`, when
supplied, must match. Every intake SELECT/INSERT/UPDATE/DELETE includes that company
identity. Database credentials are trusted server credentials; this is application
tenant isolation, not PostgreSQL row-level security for direct database clients.

Provision with a lowercase company slug (letter first, then letters/digits/hyphens,
at most 63 characters) and a validated JSON configuration. Required fields are
`business_name`, `timezone`, `opening`, `closing`, `interval_minutes`, and `services`.
Optional fields include contact email/phone, greeting, active state, confirmation
policy, booking lead time, advance window and cancellation window. Hours represent
one daily operating window; calendar/weekday scheduling is outside this phase.

Each service has a lowercase slug, positive `duration_minutes`, nonempty distinct
`keywords`, and optional industry/priority. An intake's existing `reason` selects
an exact service slug or an unambiguous keyword match. Unknown/ambiguous services
are rejected, without a fallback service. Existing scheduling calculations apply
the company's opening/closing times, interval measured from opening, durations,
timezone and booking policy. Confirmed appointments reserve availability too.

Creation returns a generated 256-bit tenant secret once in the `credential` field.
Capture it securely over HTTPS; never log the response or place the secret in a
URL. Storage contains only the SHA-256 verifier of the high-entropy token, compared
with `secrets.compare_digest`. This is not password hashing for human passwords.
Read/update responses never return the verifier or credential. A duplicate slug
returns 409 without changing the credential. Normal updates preserve it. Start
inactive if desired, then activate with the platform PUT endpoint. Deactivation
rejects subsequent requests; reactivation restores the same credential. Credential
rotation/revocation APIs and customer login portals are not part of this phase.

Configuration rejects invalid zones, hours, durations, intervals, conflicting
service keywords and unknown fields. All request-validation responses are generic
422 responses, without input echoes. Unknown, invalid, mismatched and inactive
tenant credentials receive the same generic 401. Database failures are sanitized.

Use the existing explicit migrator `init_db()` mechanism for schema setup; runtime
application startup no longer performs DDL. The companies table owns configuration
and verifier metadata. Every intake has a mandatory company foreign key and a
tenant lookup index. Existing unowned records cannot be silently assigned to a
default company: NOT NULL setup fails instead. No production migration or data
conversion was executed or authorized by this phase.

For live validation follow the isolated-integration contract. Use generated
synthetic credentials in memory and synthetic companies only. The workflow test
uses the real provisioning/authentication/endpoints with independently guarded
runtime connections. It commits synthetic data to prove reconnection persistence,
then the migrator removes only the newly created test tables and owned indexes/
sequence. No customer data remains. Operator preflight and mandatory bounded
cluster shutdown remain required; port 5432 is always outside test scope.

## Scheduling correction

Appointments preserve their instant in a required `scheduled_at TIMESTAMPTZ`
column and their company-local date, time and UTC offset in the existing textual
time fields. Time-only input resolves to the current company-local date; explicit
datetimes are converted to the company timezone. Malformed dates, nonexistent
local times and subminute requests are rejected. Conflict reads include all reserving appointments for the authenticated tenant.
Overlap compares UTC start/end instants from scheduled_at and elapsed service
duration, so timezone changes and local midnight cannot hide reservations.
Adjacent intervals remain bookable; local hours and grid rules still apply.

Booking admission locks the authenticated company's row with `FOR UPDATE`, then
rechecks overlapping reservations and inserts on the same connection/transaction.
Requests for different companies use different locks. A competing losing request
rolls back and returns sanitized `slot_unavailable`. Status changes into reserving
states acquire the same lock and recheck conflicts, excluding their own record.
The safeguard spans application instances and requires no new runtime privileges.

Explicit migrator initialization adds the required timestamp column. Existing
undated rows cannot be silently converted: setup fails until a separately reviewed
data conversion supplies their true dates. No production conversion was performed.
The focused live concurrency test coordinates real prechecks concurrently; it does
not serialize requests. PostgreSQL admission must select the single winner.
