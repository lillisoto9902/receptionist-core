# Receptionist Core - Phase 12E Stable State

## Current Stable Commits

* cd491da - Phase 12C enforce booking window settings
* e3b6901 - Add Phase 12C stable state snapshot
* 56240ab - Connect runtime confirmation settings to intake status
* 247a55b - Add Phase 12D stable state snapshot
* 4662c92 - Enforce runtime cancellation window

---

## Completed Through Phase 12E

### Phase 11

* Demo dashboard
* Business configuration architecture
* Runtime settings architecture
* Stable-state documentation process

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
* timezone-aware booking validation
* availability filtering
* invalid preferred_time protection
* clean error responses

### Phase 12D

* determine_initial_booking_status()
* auto_confirm support
* confirmation_required support
* needs_confirmation status
* slot reservation support for needs_confirmation

### Phase 12E

* get_cancellation_window_hours()
* can_cancel_booking()
* fetch_intake_by_id()
* runtime cancellation validation
* cancellation_window_hours enforcement
* clean cancellation rejection responses
* cancellation status protection

---

## Runtime Settings

* auto_confirm: Controls whether valid available bookings can be scheduled automatically.
* confirmation_required: Controls whether valid available bookings must enter needs_confirmation instead of scheduled.
* deposits_enabled: Present in runtime settings; deposit behavior is not yet implemented.
* notifications_enabled: Present in runtime settings; notification behavior is not yet implemented.
* cancellation_window_hours: Controls whether a cancellation request is allowed based on how soon the appointment begins.
* booking_lead_time_hours: Controls the minimum lead time required before a requested appointment can be booked.
* max_advance_booking_days: Controls the maximum number of days into the future an appointment can be requested.
* timezone: Controls the business timezone used by runtime booking and cancellation validation.

---

## Current Booking Lifecycle

Create Intake
-> booking window validation
-> availability validation
-> confirmation rules
-> appointment status assignment
-> save

Cancellation Request
-> fetch booking
-> cancellation window validation
-> status update
-> save

---

## Appointment Statuses

* pending: Used for intake requests that do not yet have a scheduled appointment time.
* needs_confirmation: Used for valid available bookings that require confirmation before being treated as fully scheduled.
* scheduled: Used for bookings that are immediately accepted as scheduled.
* confirmed: Used when an appointment has been explicitly confirmed.
* checked_in: Used when a client has arrived or been checked in.
* completed: Used when an appointment has finished.
* cancelled: Used when an appointment has been cancelled.
* no_show: Used when a client missed the appointment.

---

## Verified Behaviors

### Available Booking

* scheduled
* needs_confirmation

### Missing preferred_time

* needs_selection

### Invalid preferred_time

```json
{
  "status": "error",
  "message": "Invalid preferred_time format"
}
```

### Slot Unavailable

* slot_unavailable

### Cancellation Allowed

* appointment_status = cancelled

### Cancellation Blocked

```json
{
  "status": "error",
  "message": "Cancellation window has passed"
}
```

### Booking Window Enforcement

* booking_lead_time_hours
* max_advance_booking_days

---

## Environment Status

* FastAPI operational
* PostgreSQL operational
* DATABASE_URL operational
* ADMIN_API_TOKEN operational
* /settings operational
* scripts/start-dev.ps1 operational

---

## Architecture Notes

Runtime settings are still held in the in-memory BUSINESS_SETTINGS dictionary and read through get_business_setting(). The /settings endpoint remains protected by ADMIN_API_TOKEN.

Scheduling behavior now uses runtime settings across three layers:

* Booking windows reject requests inside booking_lead_time_hours or beyond max_advance_booking_days.
* Confirmation rules assign scheduled or needs_confirmation based on auto_confirm and confirmation_required.
* Cancellation rules reject cancellation attempts when cancellation_window_hours has passed.

The current cancellation behavior is enforced through the existing PUT /intakes/{request_id}/status endpoint. No separate cancellation endpoint exists.

The needs_confirmation status holds appointment slots so pending confirmations cannot be double-booked.
