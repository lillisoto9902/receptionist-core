# RECEPTIONIST CORE — PHASE 13A-R1 COMPLETION SNAPSHOT

## Product

Receptionist Core

## Phase

Phase 13A-R1 — Non-ASCII Authentication Correction

## Completion date

September 15, 2026

## Objective

Correct the security defect where non-ASCII bearer-token input raised an unhandled `TypeError`, preserve constant-time comparison and generic failure behavior, and add focused repeatable authentication tests.

## Starting baseline

- Branch: `main`
- Starting HEAD: `3b75e44c44a1cbd60c8942ef1193ca9e667c2cf5`
- Starting HEAD subject: `Phase 13A API security hardening`
- Branch was ahead of `origin/main` by one pre-existing commit, relative to the local tracking reference.
- The existing commit was not amended.
- Phase 13A-R1 changes remain uncommitted pending Project Owner approval.

## Approved scope

- Inspect `require_admin_auth()` and the approved Phase 13A security documentation.
- Apply the smallest correction for arbitrary bearer-token text, including non-ASCII Unicode, without an unhandled comparison `TypeError`.
- Preserve `secrets.compare_digest()`, generic 401 failures, the Bearer challenge, valid-credential success, generic 500 for missing server configuration, and credential non-disclosure.
- Add focused standard-library `unittest` coverage for missing/malformed authorization, empty credentials, incorrect ASCII and Unicode, mixed Unicode, correct credentials, missing server configuration, generic details, and credential non-disclosure.
- Run focused tests, Python compilation, safe directly relevant Phase 13A checks, and final diff/scope review.
- Use synthetic credentials only; do not read real `.env` values or add dependencies.

## Out-of-scope protections

No scheduling, database, tenancy, onboarding, configuration, dependency, dashboard, integration, migration, or unrelated refactoring work was performed. No unrelated cleanup was performed.

## Functionality completed

- Non-ASCII submitted bearer credentials fail safely; the comparison no longer produces an unhandled `TypeError`.
- Generic unauthorized behavior and the `WWW-Authenticate: Bearer` challenge are preserved.
- Missing or empty server-token configuration fails closed with generic HTTP 500.
- Constant-time credential comparison remains in use.
- Credential values are not disclosed by authentication responses or observed test output.
- A focused standard-library authentication test suite now exists.

## Root cause

`secrets.compare_digest()` rejects unsupported non-ASCII string comparisons with `TypeError`. The correction wraps only the comparison call, catches only `TypeError`, and treats that comparison failure as invalid authentication. Other exception types are not suppressed. The comparison result still directly controls authorization.

## Files/components changed

Statistics relative to starting HEAD, including untracked files as additions:

| File | Diff statistics |
|---|---|
| `app/main.py` | 6 insertions, 1 deletion; authentication function only |
| `tests/test_admin_auth.py` | 97 insertions, 0 deletions; new 97-line test file |
| `docs/architecture/block-status-2026-09-phase13a-r1-complete.md` | 190 insertions, 0 deletions; new 190-line snapshot |
| Total | 293 insertions, 1 deletion across 3 files |

Ordinary `git diff --stat` reports only the tracked application change until the new files are staged; the full statistics above include both untracked files.

## Acceptance-criteria results

| # | Approved acceptance criterion | Result |
|---|---|---|
| 1 | Non-ASCII bearer input returns approved generic 401 behavior without raising an unhandled TypeError. | PASS |
| 2 | Missing, malformed, empty, incorrect ASCII, and incorrect Unicode credentials fail closed. | PASS |
| 3 | Correct synthetic credentials succeed. | PASS |
| 4 | Missing server configuration returns approved generic 500. | PASS |
| 5 | Constant-time comparison remains in use. | PASS |
| 6 | No credential value appears in an error response or test output. | PASS |
| 7 | All new authentication tests pass. | PASS |
| 8 | `python -m py_compile app/main.py` passes. | PASS |
| 9 | Implementation diff contains only the narrowly approved authentication correction and focused tests. This snapshot is the separately authorized Block 4 documentation addition. | PASS |
| 10 | No database, scheduling, tenant, onboarding, or unrelated behavior is changed. | PASS |

## Validation performed

| Command or check | Expected result | Actual result |
|---|---|---|
| `python -m unittest discover -s tests -v` | All 13 tests pass | PASS: 13 tests, zero failures/errors/skips |
| `python -m py_compile app/main.py` | Exit 0 | PASS: exit 0 |
| `git diff --check` | No whitespace errors | PASS: exit 0; Git reports an LF-to-CRLF normalization warning |
| Isolated Phase 13A regression checks, executed using a PowerShell here-string piped to `python -B -` during Block 2 | Existing relevant protections preserved without database access | PASS: nine protected routes retain authentication, debug route absent, health and static demo checks pass |
| Engineer Review diff inspection: `git diff -- app/main.py tests/test_admin_auth.py`, plus full untracked test-file inspection | Approved scope only | PASS: reviewed in Block 3 |
| AST comparison against `git show HEAD:app/main.py`, executed using `python -B -` during Block 2 | Application AST outside `require_admin_auth()` unchanged | PASS; evidence considered in Engineer Review |

The three explicit validation commands were rerun during Block 4 after creating this snapshot. Isolated regression and AST results above are prior verification evidence, not claims of new live integration tests. The final file inventory and Git status were also inspected.

## Test results

- 13 tests passed.
- Zero failures.
- Zero errors.
- Zero skips.
- No database or live server required.
- Synthetic credentials only, generated at runtime.
- Environment, output streams, logging handler, and comparison mock are restored through test cleanup/context managers.

## Security validation

- Authentication fails closed.
- Non-ASCII client credential input does not produce an unhandled comparison exception.
- Constant-time comparison remains in use for supported strings.
- Error details remain generic; unauthorized responses retain the Bearer challenge.
- Credential values are not logged, printed, or returned by the authentication implementation; passing test output contains no credentials.
- Real `.env` values were not read.

## Engineer Review

`ENGINEER REVIEW: PASS`

No Critical or Major findings were identified. Review recorded one nonblocking Minor test limitation and two informational Notes. All acceptance criteria passed. Review created no tracked changes.

## Known limitations

1. The constant-time regression test proves that `compare_digest()` is called, but does not independently prove that every future implementation uses its return value correctly. Current code inspection confirms correct use. This remains the nonblocking Minor finding.
2. Non-ASCII server-configured administrative tokens remain unsupported and fail closed, including identical submitted non-ASCII tokens. Operational administrative tokens should remain ASCII.
3. Tests exercise the authentication dependency directly rather than live HTTP transport.
4. Existing case-sensitive `Bearer ` parsing and whitespace behavior remain unchanged.

These limitations are not resolved by this phase. Constant-time credential comparison does not imply a constant-time entire HTTP request path.

## Deferred findings

The following remain deferred and unchanged:

- Scheduling date handling.
- Active appointment status handling.
- Opening-hours enforcement.
- Database lookup fail-open behavior.
- Double-booking concurrency risk.
- Tenant architecture.
- Industry selection.
- Onboarding.
- Tenant isolation.
- Automated integration testing.

## Known defects

No known defect remains within the narrowly approved Phase 13A-R1 acceptance criteria. This does not resolve or certify the deferred repository defects listed above; the known limitations also remain in effect.

## Database/migration changes

None.

## Dependency changes

None.

## Deployment state

Not deployed. Not pushed. Existing and corrective work remain local.

## Current branch

`main`

## Local commit

`PENDING PROJECT OWNER APPROVAL`

The Phase 13A-R1 commit hash must be captured in the subsequent handoff after the approved local commit is created. No Phase 13A-R1 commit exists at snapshot completion.

## Git status

Final `git status --short --branch` output after creating the snapshot:

```text
## main...origin/main [ahead 1]
 M app/main.py
?? docs/architecture/block-status-2026-09-phase13a-r1-complete.md
?? tests/
```

Nothing is staged. The only untracked source/documentation files are the focused test file and this snapshot. Ignored Python caches are retained; no cleanup was performed.

## Recommended next action

1. Project Owner reviews the Completion Snapshot.
2. Project Owner authorizes the local Phase 13A-R1 commit.
3. Developer creates the approved local commit without amending the existing Phase 13A commit.
4. Developer verifies the working tree is clean.
5. Handoff returns for Senior Engineer push authorization.
6. No next phase begins until remote verification and explicit authorization.
