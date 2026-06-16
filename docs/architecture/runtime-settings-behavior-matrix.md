# Runtime Settings Behavior Matrix

## Settings

| Setting | Purpose | Default value | Endpoint(s) affected | Current implementation status | Verification status |
|---------|---------|---------------|----------------------|-------------------------------|---------------------|
| auto_confirm | Controls whether successful scheduled intakes are immediately confirmed. | false | POST /intake | Implemented for successful scheduled intake creation. | Verified through runtime intake status behavior. |
| confirmation_required | Controls the confirmation policy considered during successful scheduled intake creation. | true | POST /intake | Implemented for successful scheduled intake creation. | Verified through runtime intake status behavior. |
| booking_lead_time_hours | Prevents appointment requests inside the configured minimum lead-time window. | 2 | POST /intake, POST /availability | Implemented for booking-window validation and availability filtering. | Verified through lead time enforcement. |
| max_advance_booking_days | Prevents appointment requests beyond the configured future booking window. | 30 | POST /intake, POST /availability | Implemented for booking-window validation and availability filtering. | Verified through maximum advance booking enforcement. |
| deposits_enabled | Indicates whether deposit behavior should be active for future appointment workflows. | false | POST /intake, PUT /intakes/{request_id}/status | Present in runtime settings and decision response metadata; not yet connected to deposit workflow behavior. | Present and non-blocking; future integration planned. |
| notifications_enabled | Indicates whether notification behavior should be active for appointment workflows. | false | POST /intake, PUT /intakes/{request_id}/status | Present in runtime settings and decision response metadata; not yet connected to notification delivery. | Present and non-blocking; future integration planned. |
| cancellation_window_hours | Defines how close to an appointment cancellation remains allowed. | 24 | PUT /intakes/{request_id}/status | Implemented for cancellation status updates. | Verified through cancellation-window behavior. |
| timezone | Defines the business timezone used when evaluating requested appointment times. | America/New_York | POST /intake, POST /availability, PUT /intakes/{request_id}/status | Implemented for booking-window and cancellation-time calculations. | Verified through booking-window behavior. |

## Intake Status Matrix

| auto_confirm | confirmation_required | expected appointment_status |
|--------------|----------------------|-----------------------------|
| false | true | scheduled |
| true | true | confirmed |
| false | false | scheduled |
| true | false | confirmed |

## Booking Window Verification

### Lead Time Enforcement

- booking_lead_time_hours is applied before successful intake creation.
- Requested times inside the configured lead-time window are rejected.
- POST /intake returns slot_unavailable when the requested time violates lead-time rules.
- POST /availability filters out options that violate lead-time rules.

### Maximum Advance Booking Enforcement

- max_advance_booking_days is applied before successful intake creation.
- Requested times beyond the configured maximum advance window are rejected.
- POST /intake returns slot_unavailable when the requested time exceeds the maximum advance window.
- POST /availability returns no available options for requests beyond the maximum advance window.

## Known Future Integrations

- deposits_enabled -> Phase 13+
- notifications_enabled -> Phase 13+
