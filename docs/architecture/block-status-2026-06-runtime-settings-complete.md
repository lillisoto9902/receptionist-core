# Runtime Settings Initiative Complete

## Scope Completed

### Phase 12A

Runtime settings foundation

### Phase 12B

Developer runtime workflow

### Phase 12C

Booking window enforcement

### Phase 12D

Confirmation workflow

### Phase 12E

Cancellation workflow

### Phase 12F

Notification decision architecture

### Phase 12G

Deposit decision architecture

---

## Current Runtime Settings

* auto_confirm
  * Purpose: Controls whether valid available intakes can become scheduled immediately.
  * Behavior controlled: Initial appointment status assignment during successful intake creation.
  * Helper functions: determine_initial_booking_status(), get_business_setting()

* confirmation_required
  * Purpose: Controls whether valid available intakes require human or business confirmation.
  * Behavior controlled: Initial appointment status assignment to needs_confirmation unless auto confirmation is enabled and confirmation is not required.
  * Helper functions: determine_initial_booking_status(), get_business_setting()

* deposits_enabled
  * Purpose: Controls runtime deposit decision output.
  * Behavior controlled: deposit_decision response data on successful intake creation.
  * Helper functions: get_deposits_enabled(), should_require_deposit(), build_deposit_decision()

* notifications_enabled
  * Purpose: Controls runtime notification decision output.
  * Behavior controlled: notification_decision response data on successful intake creation and successful status updates.
  * Helper functions: get_notifications_enabled(), should_send_notifications(), build_notification_decision()

* cancellation_window_hours
  * Purpose: Controls whether an appointment can still be cancelled.
  * Behavior controlled: Cancellation requests through the existing appointment status update endpoint.
  * Helper functions: get_cancellation_window_hours(), can_cancel_booking()

* booking_lead_time_hours
  * Purpose: Controls the minimum time required between now and a requested booking.
  * Behavior controlled: Intake booking validation and availability filtering.
  * Helper functions: get_booking_lead_time_hours(), get_booking_window_message(), slot_passes_booking_window()

* max_advance_booking_days
  * Purpose: Controls how far into the future clients can book.
  * Behavior controlled: Intake booking validation and availability filtering.
  * Helper functions: get_max_advance_booking_days(), get_booking_window_message(), slot_passes_booking_window()

* timezone
  * Purpose: Defines the business timezone for runtime date and time validation.
  * Behavior controlled: Booking-window and cancellation-window calculations.
  * Helper functions: get_business_timezone(), get_business_now(), parse_requested_datetime()

---

## Runtime-Controlled Features Completed

### Booking Window Control

* booking_lead_time_hours
* max_advance_booking_days
* Requested appointments inside the lead-time window are rejected.
* Requested appointments beyond the maximum advance window are rejected.
* Availability options are filtered through the same booking-window rules.

### Confirmation Control

* determine_initial_booking_status()
* auto_confirm
* confirmation_required
* Valid available intakes become scheduled only when auto_confirm is true and confirmation_required is false.
* Otherwise, valid available intakes become needs_confirmation.

### Cancellation Control

* get_cancellation_window_hours()
* can_cancel_booking()
* Cancellation requests are allowed only when the appointment is outside the configured cancellation window.
* Cancellation requests inside the configured window return a clean error response.

### Notification Control

* get_notifications_enabled()
* should_send_notifications()
* build_notification_decision()
* Successful intake creation and successful status updates include notification decision output.
* No notification delivery is performed.

### Deposit Control

* get_deposits_enabled()
* should_require_deposit()
* build_deposit_decision()
* Successful intake creation includes deposit decision output.
* No payment collection is performed.

---

## Current Booking Lifecycle

Create Intake
-> validate preferred_time format
-> booking window validation
-> availability validation
-> confirmation rules
-> appointment status assignment
-> notification decision evaluation
-> deposit decision evaluation
-> database save
-> response

Availability Request
-> validate preferred_time format
-> booking window validation
-> availability filtering
-> response

Cancellation Request
-> validate requested status
-> fetch booking
-> cancellation window validation
-> status update
-> notification decision evaluation
-> database save
-> response

---

## Verified Behaviors

### Phase 12C

* booking_lead_time_hours rejects bookings inside the lead-time window.
* max_advance_booking_days rejects bookings beyond the maximum advance window.
* availability with preferred_time = null returns available options.
* malformed preferred_time values return a clean error response.
* malformed preferred_time values do not produce 500 errors.

### Phase 12D

* valid available bookings return scheduled when auto_confirm is true and confirmation_required is false.
* valid available bookings return needs_confirmation when auto_confirm is false or confirmation_required is true.
* needs_confirmation is a supported appointment status.
* needs_confirmation bookings hold their slots.

### Phase 12E

* cancellation outside cancellation_window_hours succeeds.
* cancellation inside cancellation_window_hours returns:

```json
{
  "status": "error",
  "message": "Cancellation window has passed"
}
```

* successful cancellation sets appointment_status to cancelled.
* invalid preferred_time behavior remains unchanged.
* missing preferred_time behavior remains unchanged.

### Phase 12F

* notifications_enabled = false returns:

```json
{
  "notifications_enabled": false,
  "notification_pending": false
}
```

* notifications_enabled = true returns:

```json
{
  "notifications_enabled": true,
  "notification_pending": true
}
```

* notification_decision appears on successful intake creation.
* notification_decision appears on successful appointment status updates.

### Phase 12G

* deposits_enabled = false returns:

```json
{
  "deposits_enabled": false,
  "deposit_required": false
}
```

* deposits_enabled = true returns:

```json
{
  "deposits_enabled": true,
  "deposit_required": true
}
```

* deposit_decision appears on successful intake creation.
* notification_decision remains present.
* cancellation behavior remains intact.

---

## Environment Status

* FastAPI operational
* PostgreSQL operational
* DATABASE_URL operational
* ADMIN_API_TOKEN operational
* .env workflow operational
* scripts/start-dev.ps1 operational
* /settings endpoint operational and protected

---

## Architecture Boundaries

The Runtime Settings Initiative intentionally does not implement:

* SMS delivery
* Email delivery
* Payment processors
* Deposit collection
* Reminder scheduling
* Background workers

The current architecture establishes runtime decisions and response outputs only. Future integrations can attach to the decision helpers without changing the core scheduling rules.

---

## Current Stable Commit Chain

* cd491da - Phase 12C enforce booking window settings
* e3b6901 - Add Phase 12C stable state snapshot
* 56240ab - Connect runtime confirmation settings to intake status
* 247a55b - Add Phase 12D stable state snapshot
* 4662c92 - Enforce runtime cancellation window
* 449a2c5 - Add Phase 12E stable state snapshot
* d2440c5 - Add runtime notfication decision logic
* a84588b - Add Phase 12F stable state snapshot
* ca64afa - Add runtime deposit decision logic

---

## Recommended Next Major Initiative

Phase 13

Operational Automation Layer

Potential areas:

* reminder architecture
* notification providers
* deposit collection integration
* calendar integrations
* reporting enhancements
* audit history
