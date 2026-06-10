# Runtime Business Settings Architecture

## 1. Business Settings Overview

Receptionist Core should support runtime business configuration so the same scheduling, intake, and appointment workflow engine can be reused across different businesses and industries without changing application code.

Future business settings should include:

- Deposits Enabled
- Auto Confirm Appointments
- Confirmation Required
- Reminder Notifications Enabled
- Cancellation Window Hours
- No Show Tracking Enabled
- Business Time Zone
- Business Hours
- Booking Lead Time
- Maximum Advance Booking Window

These settings should act as runtime rules that influence appointment behavior, booking eligibility, confirmation flow, notification behavior, and future payment requirements. The core engine should remain generic, while each business supplies its own operational policy through configuration.

## 2. Deposit System Architecture

The future deposit system should allow businesses to require payment before an appointment is confirmed. Deposit rules should be configurable per business and should not be hardcoded into scheduling or intake logic.

Deposit configuration should support:

- Deposit Required
- Deposit Amount
- Deposit Type
  - Fixed Amount
  - Percentage

Deposit status should support:

- Not Required
- Pending
- Paid
- Refunded

Recommended workflow:

```text
Appointment Created
        |
        v
Deposit Required?
        |
        v
Pending Deposit
        |
        v
Deposit Paid
        |
        v
Appointment Confirmed
```

When deposits are disabled or not required, appointments may continue through the standard confirmation path. When deposits are required, appointment confirmation should wait until the deposit status becomes `Paid`, unless a business-specific setting allows provisional confirmation.

Deposit processing itself should remain separate from appointment creation. The appointment workflow should only consume deposit state and react to state transitions.

## 3. Notification Architecture

The future notification system should publish appointment and payment-related events to configurable delivery channels. Notification behavior should be driven by business settings and event state, not embedded directly in intake, scheduling, or status update logic.

Supported channels should include:

- Email
- SMS
- Webhook

Supported events should include:

- Appointment Created
- Appointment Confirmed
- Appointment Cancelled
- Appointment Completed
- Deposit Required
- Deposit Received
- Reminder Due

Notifications should be event-based. Core workflows should emit or record meaningful business events, and the notification engine should decide which channels are enabled, which templates apply, and whether delivery is allowed for the current business configuration.

## 4. Booking Integration Architecture

Receptionist Core should eventually support external booking providers through adapter-style integrations. The internal appointment model and workflow should remain stable while provider-specific logic is isolated behind integration modules.

Future integrations may include:

- Calendly
- Acuity
- Square Appointments
- GlossGenius
- Vagaro
- Booksy

Each integration should be responsible for translating Receptionist Core appointment intent into the provider's booking, availability, cancellation, and status semantics. Provider adapters should not leak provider-specific behavior into intake or scheduling logic.

## 5. Runtime Configuration Strategy

Business settings should not be hardcoded because different businesses need different operating rules. A salon, med spa, repair shop, consultant, or fitness studio may all use the same receptionist engine while requiring different hours, time zones, deposit policies, cancellation rules, reminder preferences, and booking windows.

Runtime configuration allows the engine to remain reusable. Instead of forking the application for each industry, the same core code can load business-specific settings and apply them during availability checks, appointment creation, confirmation decisions, reminder scheduling, and future integration routing.

Settings should be loaded at runtime from a durable configuration source. The application should read the active business settings before applying configurable workflow decisions. To support operational reliability, the settings layer should define defaults, validate allowed values, and expose a consistent in-memory representation to the rest of the application.

The runtime configuration layer should be treated as a business policy boundary:

- Scheduling asks the settings layer for hours, lead time, booking windows, and time zone.
- Appointment workflow asks the settings layer for confirmation and deposit rules.
- Notifications ask the settings layer which channels and events are enabled.
- Integrations ask the settings layer which provider, credentials, and sync behavior are active.

## 6. Recommended Phase Order

Phase 12: Business Settings Engine

Create the runtime settings model, loading strategy, validation rules, and default behavior.

Phase 13: Deposit Workflow

Add deposit policy evaluation, deposit statuses, and appointment workflow transitions based on deposit state.

Phase 14: Notification Engine

Add event-driven notification routing for email, SMS, and webhook delivery.

Phase 15: Booking Integrations

Add provider adapters for external booking systems while preserving the internal appointment workflow.
