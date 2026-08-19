# Phase 13A API Access Control and Authentication Hardening Plan

## Purpose

Define the approved minimal hardening pass for Receptionist Core's existing administrative bearer-token boundary. Phase 13A preserves the current architecture and does not implement a new authentication system.

This is an engineering specification only. It does not implement any runtime change.

## Scope

Phase 13A implementation is limited to these five areas:

1. Use a constant-time Python standard-library comparison for `ADMIN_API_TOKEN`.
2. Normalize administrative authentication failures so client responses do not reveal unnecessary credential or configuration state.
3. Eliminate production exposure of `DATABASE_URL` contents or previews through `GET /debug/database-url`.
4. Resolve the access-classification ambiguity of the static `GET /admin/dashboard/demo` route with the minimal treatment documented below.
5. Replace raw internal exception details returned by affected API handlers with safe client responses where those details can disclose database, infrastructure, or implementation information.

Public endpoint abuse protection is explicitly outside this phase and assigned to Phase 13B.

## Current verified security baseline

Repository review was performed against `main` on 2026-08-17.

- The worktree was clean before the Phase 13A document was created.
- `.env` is ignored by `.gitignore`, is not tracked, and has no commit history visible through `git log --all -- .env`.
- `.env` contents were not inspected or changed during review.
- No obvious live credential appears in the tracked files reviewed. `.env.example` contains placeholders for `DATABASE_URL` and `ADMIN_API_TOKEN`.
- `DATABASE_URL` and `ADMIN_API_TOKEN` are read from process environment variables in `app/main.py`.
- All explicit database-backed settings, statistics, intake retrieval/filter, status-update, and deletion routes use `Depends(require_admin_auth)`.
- Public receptionist routes required for normal operation are `GET /`, `GET /health`, `POST /intake`, and `POST /availability`.
- FastAPI's default `GET /openapi.json`, `GET /docs`, and `GET /redoc` routes are implicitly enabled.
- The repository contains no application or deployment-layer rate limiting, throttling, body-size controls, or explicit additional public input limits. These observations are retained for Phase 13B and are not Phase 13A implementation requirements.

### Baseline discrepancy

The supplied baseline did not mention `GET /admin/dashboard/demo`. The implementation contains this additional unauthenticated route.

Code review confirms that it returns a hardcoded HTML string labeled as demo data. It does not query the database, call another API, execute client-side data fetching, or include real customer/contact records. It therefore does not currently expose administrative or customer data. Its `/admin` path nevertheless requires an explicit classification to prevent future ambiguity.

No other conflict with the supplied baseline was found.

## Existing authentication behavior

`require_admin_auth()` currently:

1. Reads `ADMIN_API_TOKEN` from the environment on each protected request.
2. Returns HTTP 500 with `ADMIN_API_TOKEN is not configured` when the variable is absent or empty.
3. Requires an `Authorization` value beginning with the exact string `Bearer `.
4. Removes the prefix, trims the submitted token, and compares it to the configured value with ordinary Python string inequality.
5. Returns HTTP 401 with `Missing or invalid authorization header` for a missing or malformed header.
6. Returns HTTP 403 with `Invalid admin token` for a well-formed header containing the wrong token.
7. Returns `True` and permits the endpoint when the strings match.

This shared-secret control is functional and proportionate to the current application scope. The comparison and response behavior require targeted hardening, but the authentication model itself does not require replacement.

## Endpoint access-control matrix

| Endpoint | Current access | Data/action | Phase 13A disposition |
|---|---|---|---|
| `GET /` | Public | Service status and version | Remain public; unchanged. |
| `GET /health` | Public | Basic service liveness | Remain public; unchanged. |
| `GET /settings` | Bearer token | Business runtime settings | Remain protected; receive hardened shared authentication behavior. |
| `GET /dashboard/stats` | Bearer token | Aggregate intake counts | Remain protected; sanitize raw internal failures. |
| `GET /admin/dashboard/demo` | Public | Static hardcoded demo HTML | Remain public as an explicitly classified static demo. Add no new authentication system. Validate that it stays disconnected from live data. |
| `GET /debug/database-url` | Bearer token | Configuration presence and first 25 characters of `DATABASE_URL` | Remove the route as the approved minimal treatment. No production response may expose a URL preview or content. |
| `POST /intake` | Public | Creates an intake and returns scheduling/record data | Remain public. Sanitize raw internal failures only. Abuse and additional validation controls are Phase 13B. |
| `POST /availability` | Public | Returns candidate appointment slots | Remain public. Abuse and additional validation controls are Phase 13B. |
| `GET /intakes` | Bearer token | Lists full customer/contact and appointment records | Remain protected; sanitize raw internal failures. |
| `GET /intakes/status/{status}` | Bearer token | Filtered full intake records | Remain protected; sanitize raw internal failures. |
| `GET /intakes/service/{service_type}` | Bearer token | Filtered full intake records | Remain protected; sanitize raw internal failures. |
| `GET /intakes/priority/{priority}` | Bearer token | Filtered full intake records | Remain protected; sanitize raw internal failures. |
| `GET /intakes/{request_id}` | Bearer token | One full intake record | Remain protected; sanitize raw internal failures. |
| `PUT /intakes/{request_id}/status` | Bearer token | Changes status and returns an intake record | Remain protected; sanitize raw internal failures. |
| `DELETE /intakes/{request_id}` | Bearer token | Deletes an intake record | Remain protected; sanitize raw internal failures. |
| `GET /openapi.json`, `GET /docs`, `GET /redoc` | Public, framework-provided | Route and schema discovery | Unchanged in Phase 13A. Future production exposure policy is deferred. |

No sensitive database-backed administrative endpoint was found without `require_admin_auth()`. No unauthenticated route retrieves, changes, or deletes an existing intake record by identifier.

## Findings

### F1 — Administrative data routes consistently use the existing authentication dependency

All explicit settings, statistics, intake collection/filter/read, status-update, deletion, and database-debug routes classified as administrative use `Depends(require_admin_auth)`.

Disposition: retain the boundary and regression-test it in Phase 13A. No redesign is required.

### F2 — Token comparison is not constant-time

The submitted token is checked with ordinary string inequality.

Disposition: address in Phase 13A with `secrets.compare_digest()`. This is available in the Python standard library and requires no dependency.

### F3 — Authentication responses reveal avoidable state

The current 401, 403, and detailed 500 responses distinguish malformed credentials, an incorrect token, and missing server configuration.

Disposition: address in Phase 13A. Missing, malformed, empty, and incorrect client credentials receive one generic unauthorized response. Missing server configuration continues to fail closed but returns a generic server error without naming the variable or revealing configuration state. Actionable configuration detail belongs only in safe server-side diagnostics.

### F4 — The database debug route exposes part of a secret-bearing value

`GET /debug/database-url` returns the first 25 characters of `DATABASE_URL`. A database URL can contain a username, password, host, port, and database name; a fixed prefix is not safe redaction.

Disposition: address in Phase 13A by removing the route. This is simpler and safer than introducing a new environment-mode mechanism solely to gate it. Local configuration should be diagnosed from the server environment/startup tooling rather than through a client-facing URL. Update documentation that currently advertises the preview.

### F5 — Raw exception strings are returned to API clients

Multiple handlers interpolate `str(e)` into API responses. Database or driver exceptions can disclose hosts, database names, SQL details, or infrastructure state. This includes handlers reachable through public routes.

Disposition: address in Phase 13A with stable generic client messages. Preserve useful server-side diagnostics without logging secrets, authorization headers, connection URLs, or customer/contact payloads. Do not perform unrelated error-handling refactoring.

### F6 — The public dashboard demo has an ambiguous path but static content

`GET /admin/dashboard/demo` is unauthenticated, but its implementation is a static hardcoded HTML response with sample numbers. It performs no database access, contains no customer/contact records, and makes no live API request.

Disposition: the approved minimal Phase 13A treatment is to retain it as a public static demo and document that classification. Validation must prove it remains static and disconnected from live data. Any future change that connects it to protected APIs or live administrative/customer data requires the existing admin authentication dependency and a fresh access-control review.

### F7 — Public intake and availability routes have abuse-protection gaps

The two necessary public POST routes have no visible rate limiting, request throttling, body-size limits, or additional public input bounds. `POST /intake` can create stored records, while `POST /availability` can be automated to consume resources or enumerate availability.

Disposition: important but explicitly deferred in full to Phase 13B, Public Endpoint Abuse Protection. Phase 13A must not implement these controls.

### F8 — The current shared admin token remains acceptable for this scope

A high-entropy, environment-injected bearer token over HTTPS is a proportionate minimal control for the current administrative API. Its lack of individual identity, scoped permissions, and overlapping rotation is acknowledged but does not justify a new authentication architecture in Phase 13A.

Disposition: retain the model. Broader identity work remains deferred unless concrete product requirements emerge.

## Risks

| Risk | Current significance | Phase disposition |
|---|---|---|
| Timing-sensitive secret comparison | Low but avoidable | Mitigate in 13A with `secrets.compare_digest()`. |
| Authentication-state disclosure | Low to moderate | Mitigate in 13A with normalized client failures and fail-closed generic server errors. |
| Database URL content disclosure | Moderate | Mitigate in 13A by removing the debug route. |
| Database/infrastructure detail in exception responses | Moderate | Mitigate in 13A with sanitized client messages. |
| Future live-data connection to a public `/admin` demo | Low now | Explicitly classify and regression-test static-only behavior in 13A. |
| Intake spam, resource exhaustion, or availability scraping | Moderate for an Internet-facing service | Address in Phase 13B; do not expand 13A. |
| Shared-token disclosure or lack of per-operator accountability | Operationally dependent | Retain current model; broader identity architecture is deferred. |

## Proposed minimal changes

Phase 13A implementation consists only of the following:

1. Import Python's standard-library `secrets` module and use `secrets.compare_digest()` for comparison of the presented token and `ADMIN_API_TOKEN`. Preserve exact secret semantics and fail closed for an unset or empty configured token.
2. Normalize client authentication failures. Missing, malformed, empty, and incorrect credentials should return the same generic HTTP 401 response. Include `WWW-Authenticate: Bearer`. A missing server token should produce a generic fail-closed server response and safe server-side diagnostic without naming or returning the missing variable to clients. Never log presented or configured tokens.
3. Remove `GET /debug/database-url` and its response behavior. Remove documentation that advertises the endpoint or a database URL preview. Do not replace it with another production-facing secret/configuration diagnostic.
4. Retain `GET /admin/dashboard/demo` as a documented public static demo. Do not add a new authentication mechanism and do not connect the page to live data. Add a focused regression check, if tests are introduced, that it contains no live customer data or API fetch behavior. Future live-data use must be protected separately.
5. Replace raw `str(e)` response content in affected handlers with stable generic messages. Keep diagnostics server-side and exclude database URLs, tokens, authorization headers, and customer/contact payloads. Limit edits to response sanitization necessary for this finding.

No public abuse controls, request-shape changes, response-contract redesign, documentation-endpoint policy change, dependency addition, or unrelated refactoring belongs in this implementation.

## Environment-secret handling relevant to Phase 13A

- Keep `.env` ignored and untracked. Never place real values in `.env.example`.
- Continue loading `ADMIN_API_TOKEN` and `DATABASE_URL` from the runtime environment.
- Use a strong, randomly generated admin token unique to each environment and transmit it only over HTTPS outside isolated local development.
- Do not place tokens, authorization headers, database URLs, or environment dumps in responses or logs.
- Rotate the shared token after suspected disclosure. A more elaborate rotation system is not part of Phase 13A.

These are operational requirements for the existing design, not an expansion into new secret-management infrastructure.

## Explicit non-goals

- No JWT.
- No OAuth.
- No RBAC.
- No user account system.
- No external identity provider.
- No new dependency unless separately and specifically approved.
- No database schema change or migration.
- No CareClerk-, healthcare-, HIPAA-, or medical-record architecture.
- No unrelated refactoring.
- No redesign of intake, availability, scheduling, or administrative workflows.
- No global authentication that would make required public receptionist routes private.
- No Phase 13B abuse-protection work in Phase 13A.

## Validation plan

Use an isolated environment, a non-production database, and synthetic contact data.

### Authentication validation

- Verify every currently protected route still rejects requests without valid administrative authentication.
- Verify no header, a wrong scheme, an empty bearer value, a malformed header, and an incorrect token all receive the same generic 401 response and `WWW-Authenticate: Bearer`.
- Verify the valid configured token succeeds on each protected route.
- Verify an unset or empty `ADMIN_API_TOKEN` fails closed and does not name the environment variable or reveal configuration details to the client.
- Verify neither presented nor configured tokens appear in response bodies or captured logs.
- Verify by code inspection or a focused unit test that equality uses `secrets.compare_digest()`; HTTP timing measurements are not proof of constant-time comparison.

### Endpoint-boundary validation

- Re-enumerate explicit application routes and compare them to the access-control matrix.
- Verify `GET /`, `GET /health`, `POST /intake`, and `POST /availability` remain publicly callable for normal product behavior.
- Verify unauthenticated callers cannot list, filter, retrieve, update, or delete existing intake records.
- Verify `GET /debug/database-url` is no longer registered and returns 404 without exposing any part of `DATABASE_URL`.
- Verify tracked documentation no longer advertises a database URL preview endpoint.
- Verify `GET /admin/dashboard/demo` remains a static hardcoded page with no database access, customer/contact data, client-side fetch, or live administrative API connection.

### Error-sanitization validation

- Force representative database failures in each affected handler and verify client responses contain no hostname, database name, SQL statement, driver detail, credential, stack information, or raw exception text.
- Verify protected and public route behavior remains otherwise unchanged.
- Verify any server-side diagnostics retain useful event context without database URLs, tokens, authorization headers, or customer/contact request bodies.

Rate limits, throttling, request-body limits, additional public input-boundary tests, and deployment abuse controls are specifically excluded from Phase 13A validation and belong to Phase 13B.

## Rollback considerations

- Keep authentication comparison/response changes, debug-route removal, and exception sanitization logically separable.
- If normalized header handling breaks a verified administrative client, restore only the required compatible parsing while retaining constant-time comparison, generic failure messages, and fail-closed behavior.
- Do not restore database URL preview behavior. Diagnose environment configuration through local server tooling.
- If exception sanitization obscures operational diagnosis, improve safe server-side logging rather than restoring raw client errors.
- The demo route requires no runtime access change under the approved treatment. If later modified to use live data, that later change must not be presented as a Phase 13A rollback.
- A rollback must never expose secrets, weaken authentication on protected intake routes, or add authentication to required public receptionist routes.

## Files expected to change during implementation

- `app/main.py` — constant-time comparison, normalized authentication failures, removal of the database debug route, and targeted exception-response sanitization. No runtime change is required for the already-static demo route unless a focused test needs a stable marker.
- `README.md` — remove the database URL preview endpoint description and keep the public/static demo classification accurate if the route is documented there.
- Existing setup/security documentation that directly advertises the removed debug behavior or describes old authentication failure behavior, if found during implementation.
- A focused test file or test directory, if tests are added using approved existing capabilities, for authentication, route absence, demo static behavior, and error sanitization.

No change is expected to `.env`, `.env.example`, the database schema, migrations, or dependency manifests.

## Phase completion criteria

Phase 13A implementation is complete only when all of the following are true:

- Administrative token equality uses `secrets.compare_digest()`.
- Missing, malformed, empty, and incorrect client credentials return one generic unauthorized response with a bearer challenge.
- An unset or empty configured admin token fails closed without disclosing its environment-variable name or configuration state to the client.
- All previously protected administrative and intake-record routes remain protected, and required public receptionist routes remain public.
- `GET /debug/database-url` is absent and no production API response exposes `DATABASE_URL` contents or previews.
- Documentation no longer advertises the removed database URL preview behavior.
- `GET /admin/dashboard/demo` is explicitly documented and verified as a public static demo with no database access, customer/contact data, or live API fetch.
- Affected handlers return generic client errors instead of raw internal exception strings that could expose database, infrastructure, or implementation detail.
- Responses and relevant diagnostics contain no tokens, authorization headers, database URLs, or customer/contact payloads introduced by error logging.
- Repeatable tests or verification evidence cover constant-time comparison use, authentication negative cases, protected/public route boundaries, debug-route removal, demo static behavior, and error sanitization.
- No new dependency, database change, identity architecture, Phase 13B abuse control, or unrelated refactoring has been introduced.

## Deferred security work

### Phase 13B — Public Endpoint Abuse Protection

The following are explicitly deferred in full to Phase 13B and must not be implemented as part of Phase 13A:

- Abuse controls for public `POST /intake`.
- Abuse controls for public `POST /availability`.
- Rate limiting.
- Request throttling and burst handling.
- Request-body size limits.
- Additional public input constraints and boundary validation.
- Deployment-layer abuse controls, including proxy/edge rate and body policies.
- Abuse monitoring, availability-enumeration mitigation, spam controls, and bot protections associated with those public routes.

### Other deferred security work

- Per-operator identities, scoped permissions, individual audit trails, user accounts, RBAC, OAuth, JWT, or external identity providers.
- Dual-token or grace-period rotation for the shared administrative credential.
- Production policy for FastAPI documentation endpoints.
- Centralized security logging, alerting, retention, automated secret scanning, and formal threat modeling.
- Network-level restrictions for administrative routes.
- Customer/contact data-retention and broader response-minimization policy.

