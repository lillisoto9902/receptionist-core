# Business Configuration Model

## 1. Business Profile

The business profile should describe the business identity and operating context used by Receptionist Core. These fields should be business-specific and should allow the same core application to represent different clients without code changes.

Example structure:

```json
{
  "business_name": "",
  "industry": "",
  "timezone": "",
  "business_hours": {},
  "contact_email": "",
  "contact_phone": ""
}
```

The `timezone` and `business_hours` fields should be treated as core scheduling inputs. Contact fields should be used by future customer-facing messages, admin displays, and integration metadata.

## 2. Booking Configuration

Booking configuration should define the business rules that control when and how appointments may be created or confirmed.

Example structure:

```json
{
  "auto_confirm": false,
  "confirmation_required": true,
  "booking_lead_time_hours": 2,
  "max_advance_booking_days": 30,
  "cancellation_window_hours": 24
}
```

These values should drive booking policy at runtime. For example, `booking_lead_time_hours` prevents bookings too close to the current time, while `max_advance_booking_days` limits how far into the future a customer can schedule.

## 3. Deposit Configuration

Deposit configuration should define default deposit behavior for the business. It should describe whether deposits are active and what default amount or calculation method should apply when a service does not define its own override.

Example structure:

```json
{
  "deposits_enabled": true,
  "default_deposit_type": "fixed",
  "default_deposit_amount": 25
}
```

The `default_deposit_type` field should support values such as `fixed` and `percentage` in a future implementation. Deposit settings should remain configuration only until a deposit workflow and payment provider are intentionally added.

## 4. Service-Level Overrides

Service-level overrides should allow individual services to inherit business defaults while changing only the settings that differ.

Example services:

- haircut
- consultation
- lash_fill
- full_set_lashes

By default, each service should inherit the business profile, booking configuration, deposit configuration, and notification configuration. Overrides should be used only when a service needs different behavior.

Examples of service-level differences may include:

- A consultation may have no deposit while a full service requires one.
- A full set of lashes may require a longer booking lead time.
- A healthcare consultation may require confirmation even if other service types auto-confirm.
- A premium service may use a higher fixed deposit or a percentage deposit.

This inheritance model keeps business-wide rules simple while allowing higher-risk, higher-cost, or longer-duration services to define stricter policies.

## 5. Notification Configuration

Notification configuration should define which delivery channels are available for business events. Each channel should be independently enabled or disabled so businesses can adopt only the communication methods they support.

Example structure:

```json
{
  "email": {
    "enabled": true
  },
  "sms": {
    "enabled": false
  },
  "webhook": {
    "enabled": false
  }
}
```

Future notification settings may also include templates, sender identities, provider credentials, retry policy, and event-specific channel preferences. The configuration model should separate whether a channel is enabled from the implementation details of delivering through that channel.

## 6. Multi-Industry Strategy

The configuration framework should allow Receptionist Core to support multiple industries with the same underlying engine.

A salon may configure service names, deposits for premium services, SMS reminders, and business hours that vary by day. Healthcare may require confirmation, longer cancellation windows, stricter booking lead times, and industry-specific service labels. Legal services may use consultations, office time zones, email-first communication, and manual confirmation. Roofing may use estimate appointments, weather-sensitive scheduling rules in future phases, and webhook handoffs to field-service tools. Consulting may use simple availability windows, no deposits, and email confirmations.

The same configuration structure can support each industry because the core concepts stay consistent:

- Business identity and contact details
- Operating hours and time zone
- Booking windows and confirmation policy
- Deposit defaults and optional overrides
- Notification channel preferences
- Service-specific behavior when business defaults are not enough

Industry-specific behavior should be expressed through configuration values and service definitions, not through duplicated application logic.

## 7. Future Runtime Loading Strategy

Business configuration should eventually be database-driven so each business can maintain its own settings without redeploying the application. The database should become the source of truth for business profile, booking policy, deposit defaults, notification preferences, and service-level overrides.

At runtime, the application should load settings for the active business before applying configurable behavior. A normalized runtime settings object should be made available to scheduling, appointment workflow, notification, deposit, and integration modules.

Cached runtime settings should be used to avoid repeated database reads for every request. The cache should preserve correctness by supporting explicit invalidation, short time-to-live windows, or reload-on-update behavior.

Per-business settings should allow multiple businesses or industry templates to use the same Receptionist Core deployment. Each request or workflow should resolve the relevant business context, load that business's configuration, and apply only those settings to the current operation.
