# Receptionist Core - Phase 12C Stable State Snapshot

## Phase

12C Runtime Behavior Layer

## Completed

- booking_lead_time_hours helper
- max_advance_booking_days helper
- booking-window enforcement
- availability filtering
- invalid preferred_time safety handling

## Verified

- /settings returns runtime settings
- /availability works with preferred_time null
- /availability returns clean error for invalid preferred_time string
- no 500 error for invalid preferred_time
- server starts using scripts/start-dev.ps1
- DigitalOcean PostgreSQL connection verified

## Current Stable Commit

PENDING_COMMIT_HASH

## Known Dependencies

- .env file required locally
- DATABASE_URL
- ADMIN_API_TOKEN
- scripts/start-dev.ps1

## Next Resume Point

Phase 12D

## Recommended Phase 12D

Connect auto_confirm and confirmation_required settings to intake status behavior.
