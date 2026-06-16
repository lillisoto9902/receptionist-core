# Receptionist Core Product Release Readiness

## Environment

- Verify .env exists
- Verify DATABASE_URL configured
- Verify ADMIN_API_TOKEN configured
- Verify scripts/start-dev.ps1 works
- Verify PostgreSQL connection succeeds

## Startup

- Start server
- Verify no startup errors
- Verify /health
- Verify /settings

## Runtime Settings

Verify:
- auto_confirm
- confirmation_required
- booking_lead_time_hours
- max_advance_booking_days
- deposits_enabled
- notifications_enabled

## Intake Testing

Verify:
- preferred_time null
- needs_selection flow
- slot selection flow
- scheduled intake flow
- invalid preferred_time handling

## Availability Testing

Verify:
- availability generation
- booking lead time enforcement
- advance booking enforcement

## Documentation

Verify:
- current-state.md
- runtime-settings-behavior-matrix.md
- phase snapshots
- local-environment.md
- developer-handoff-checklist.md

## Demo Assets

Capture:
- Swagger homepage
- /settings response
- availability response
- successful intake response
- demo dashboard

## Release Decision

Ready:
- All checks pass

Not Ready:
- Any failed verification documented

Next Phase:
12G Phase Completion Snapshot
