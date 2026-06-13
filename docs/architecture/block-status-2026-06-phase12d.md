# Receptionist Core - Phase 12D Stable State

## Current Repository State

Current stable commits:

* cd491da - Phase 12C enforce booking window settings
* e3b6901 - Add Phase 12C stable state snapshot
* 56240ab - Connect runtime confirmation settings to intake status

## Completed Through Phase 12D

### Phase 11

* Demo dashboard
* Business configuration architecture
* Runtime settings architecture
* Stable-state documentation process established

### Phase 12A

* BUSINESS_SETTINGS dictionary
* get_business_setting()
* Protected GET /settings endpoint

### Phase 12B

* .env support
* Developer startup workflow
* scripts/start-dev.ps1
* Local environment documentation
* Developer handoff documentation

### Phase 12C

* booking_lead_time_hours enforcement
* max_advance_booking_days enforcement
* timezone-aware booking validation helpers
* availability filtering
* invalid preferred_time protection
* clean error responses
* no 500 errors from malformed preferred_time values

### Phase 12D

* determine_initial_booking_status()
* runtime-controlled intake status behavior
* auto_confirm setting support
* confirmation_required setting support
* needs_confirmation appointment status
* needs_confirmation blocks slot reuse
* slot reservation logic updated

## Current Runtime Settings

The protected GET /settings endpoint currently returns these runtime settings:

* auto_confirm: Controls whether a valid available booking can be immediately scheduled.
* confirmation_required: Controls whether available bookings must enter needs_confirmation instead of scheduled.
* deposits_enabled: Present in runtime settings but not yet connected to booking behavior.
* notifications_enabled: Present in runtime settings but not yet connected to notification behavior.
* cancellation_window_hours: Present in runtime settings but not yet connected to cancellation behavior.
* booking_lead_time_hours: Enforces the minimum time between now and a requested appointment.
* max_advance_booking_days: Enforces the maximum future booking window.
* timezone: Provides the business timezone used by booking-window validation.

## Verified Behaviors

### Valid Available Booking

When:

* slot available
* preferred_time valid

Behavior:

* auto_confirm=true and confirmation_required=false -> scheduled
* auto_confirm=false OR confirmation_required=true -> needs_confirmation

### Missing preferred_time

Returns:

* needs_selection

### Invalid preferred_time

Returns:

```json
{
  "status": "error",
  "message": "Invalid preferred_time format"
}
```

### Slot Unavailable

Returns:

* slot_unavailable

### Booking Window Violations

Current enforcement:

* booking_lead_time_hours rejects requested times inside the configured lead-time window.
* max_advance_booking_days rejects requested times beyond the configured maximum future booking window.

### Availability Endpoint

Current behavior:

* preferred_time = null is supported and returns available options.
* booking-window filtering removes options that violate lead-time or maximum-advance rules.

## Environment Status

* DigitalOcean PostgreSQL connected
* DATABASE_URL operational
* ADMIN_API_TOKEN operational
* .env workflow operational
* scripts/start-dev.ps1 operational
* FastAPI server operational

## Current Architecture

Current booking flow:

Request
-> booking window validation
-> availability validation
-> runtime confirmation rules
-> appointment status assignment
-> database save

The determine_initial_booking_status() helper reads auto_confirm and confirmation_required through get_business_setting(). It returns scheduled only when auto_confirm is true and confirmation_required is false. Otherwise, it returns needs_confirmation.

## Known Appointment Statuses

* pending: Used for requests without a scheduled appointment time.
* needs_confirmation: Used for available bookings that require review or confirmation before becoming scheduled.
* scheduled: Used for bookings that are immediately accepted as scheduled.
* confirmed: Used when an appointment has been explicitly confirmed.
* checked_in: Used when a client has arrived or been checked in.
* completed: Used when the appointment has finished.
* cancelled: Used when an appointment has been cancelled.
* no_show: Used when a client missed the appointment.

## Verification Performed

Phase 12D verification completed:

* Reviewed git status before editing.
* Confirmed Phase 12C code commit exists.
* Inspected intake status logic in app/main.py.
* Ran python -m py_compile app/main.py.
* Confirmed FastAPI server was operational.
* Verified protected GET /settings returns runtime settings.
* Verified POST /availability with preferred_time null returns available options.
* Verified POST /intake with a valid available preferred_time returns needs_confirmation under current default settings.
* Verified inserted intake data stores appointment_status as needs_confirmation.
* Verified POST /availability with invalid preferred_time returns a clean error response.
* Verified POST /intake with missing preferred_time still returns needs_selection.
* Verified POST /intake with invalid preferred_time returns a clean error response.
* Confirmed git diff only contained Phase 12D-related application changes before commit.

## Recommended Resume Point

Recommend Phase 12E.

Suggested Phase 12E objective:

Create runtime-controlled cancellation behavior using:

* cancellation_window_hours

including:

* cancellation eligibility helper
* cancellation validation endpoint logic
* runtime-driven cancellation enforcement
