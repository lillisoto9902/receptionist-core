import os
import secrets
import psycopg2
from contextlib import closing, nullcontext
from datetime import datetime, time, timedelta, timezone
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from app import companies
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
from zoneinfo import ZoneInfo


app = FastAPI(
    title="Receptionist Core",
    description="A modular digital receptionist engine for intake, scheduling, and client communication.",
    version="0.1.0",
)


class SchedulingConflict(Exception):
    """A reservation conflicts with an existing appointment."""


class SchedulingDataError(Exception):
    """Reserving booking data could not be read or evaluated reliably."""


@app.exception_handler(SchedulingDataError)
async def scheduling_unavailable_handler(request, exc):
    return JSONResponse(status_code=503, content={"detail": "Scheduling unavailable"})


class IntakeRequest(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    reason: str
    preferred_time: Optional[str] = None
    source: Optional[str] = "form"


class AvailabilityRequest(BaseModel):
    reason: str
    preferred_time: Optional[str] = None


class StatusUpdate(BaseModel):
    appointment_status: str


SERVICES = {
    "haircut": {"industry": "salon", "duration_minutes": 60, "priority": "normal"},
    "coloring": {"industry": "salon", "duration_minutes": 120, "priority": "normal"},
    "styling": {"industry": "salon", "duration_minutes": 60, "priority": "normal"},
    "treatment": {"industry": "salon", "duration_minutes": 90, "priority": "normal"},
    "full_set_lashes": {"industry": "salon", "duration_minutes": 120, "priority": "normal"},
    "lash_fill": {"industry": "salon", "duration_minutes": 60, "priority": "normal"},
    "consultation": {"industry": "salon", "duration_minutes": 30, "priority": "low"},
}

VALID_APPOINTMENT_STATUSES = {
    "pending",
    "needs_confirmation",
    "scheduled",
    "confirmed",
    "checked_in",
    "completed",
    "cancelled",
    "no_show",
}

ALLOWED_INTAKE_FILTER_FIELDS = {
    "appointment_status",
    "service_type",
    "priority",
}

BUSINESS_SETTINGS = {
    "auto_confirm": False,
    "confirmation_required": True,
    "deposits_enabled": False,
    "notifications_enabled": False,
    "cancellation_window_hours": 24,
    "booking_lead_time_hours": 2,
    "max_advance_booking_days": 30,
    "timezone": "America/New_York",
}


def get_business_setting(setting_name, default=None):
    return companies.current()['configuration'].get(setting_name, default)


def determine_initial_booking_status():
    auto_confirm = bool(get_business_setting("auto_confirm", False))
    confirmation_required = bool(get_business_setting("confirmation_required", True))

    if auto_confirm and not confirmation_required:
        return "scheduled"
    return "needs_confirmation"


def determine_initial_appointment_status():
    auto_confirm = get_business_setting("auto_confirm", False)
    confirmation_required = get_business_setting("confirmation_required", True)

    if auto_confirm:
        return "confirmed"

    if confirmation_required:
        return "scheduled"

    return "scheduled"


def get_notifications_enabled():
    value = get_business_setting("notifications_enabled", False)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def should_send_notifications():
    return get_notifications_enabled()


def build_notification_decision():
    notifications_enabled = should_send_notifications()
    return {
        "notifications_enabled": notifications_enabled,
        "notification_pending": notifications_enabled,
    }


def get_deposits_enabled():
    value = get_business_setting("deposits_enabled", False)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def should_require_deposit():
    return get_deposits_enabled()


def build_deposit_decision():
    deposits_enabled = should_require_deposit()
    return {
        "deposits_enabled": deposits_enabled,
        "deposit_required": deposits_enabled,
    }


def get_booking_lead_time_hours():
    try:
        return int(get_business_setting("booking_lead_time_hours", 0) or 0)
    except (TypeError, ValueError):
        return 0


def get_max_advance_booking_days():
    try:
        return int(get_business_setting("max_advance_booking_days", 0) or 0)
    except (TypeError, ValueError):
        return 0


def get_cancellation_window_hours():
    try:
        return int(get_business_setting("cancellation_window_hours", 0) or 0)
    except (TypeError, ValueError):
        return 0


def get_business_timezone():
    timezone_name = get_business_setting("timezone", "America/New_York")
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return ZoneInfo("America/New_York")


def get_business_now():
    return datetime.now(get_business_timezone())


def parse_requested_datetime(value, now=None):
    if value is None:
        return None

    requested_value = str(value).strip()
    if not requested_value or requested_value.lower() in {"null", "none", "string"}:
        return None

    timezone = get_business_timezone()
    if now is None:
        now = get_business_now()

    try:
        parsed_datetime = datetime.fromisoformat(requested_value.replace("Z", "+00:00"))
        if parsed_datetime.tzinfo is None:
            local = parsed_datetime.replace(tzinfo=timezone)
            if datetime.fromtimestamp(local.timestamp(), timezone).replace(tzinfo=None) != parsed_datetime:
                return None
            return local
        return parsed_datetime.astimezone(timezone)
    except ValueError:
        if "T" in requested_value or " " in requested_value:
            return None

    try:
        parsed_time = time.fromisoformat(requested_value if len(requested_value.split(':')[0]) == 2 else '0' + requested_value)
    except ValueError:
        return None
    normalized_time = normalize_time_value(requested_value)
    if normalized_time is None or ":" not in normalized_time:
        return None

    try:
        hour, minute = map(int, normalized_time.split(":"))
        candidate = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone).replace(
            hour=hour,
            minute=minute, second=parsed_time.second, microsecond=parsed_time.microsecond,
        )
        if datetime.fromtimestamp(candidate.timestamp(), timezone).replace(tzinfo=None) != candidate.replace(tzinfo=None):
            return None
        return candidate
    except (TypeError, ValueError):
        return None


def is_valid_preferred_time(value):
    if value is None:
        return True

    parsed = parse_requested_datetime(value)
    return parsed is not None and parsed.second == 0 and parsed.microsecond == 0


def invalid_preferred_time_response(service_type, service):
    return {
        "status": "error",
        "service_type": service_type,
        "industry": service["industry"],
        "duration_minutes": service["duration_minutes"],
        "priority": service["priority"],
        "message": "Invalid preferred_time format",
    }


def can_cancel_booking(appointment_time, now=None):
    appointment_datetime = parse_requested_datetime(appointment_time, now)
    if appointment_datetime is None:
        return True

    if now is None:
        now = get_business_now()

    cancellation_window_hours = get_cancellation_window_hours()
    if cancellation_window_hours <= 0:
        return True

    return appointment_datetime - now >= timedelta(hours=cancellation_window_hours)


def get_booking_window_message(preferred_time):
    requested_datetime = parse_requested_datetime(preferred_time)
    if requested_datetime is None:
        return None

    return get_booking_window_message_for_datetime(requested_datetime)


def get_booking_window_message_for_datetime(requested_datetime):
    now = get_business_now()
    lead_time_hours = get_booking_lead_time_hours()
    if lead_time_hours > 0 and requested_datetime < now + timedelta(hours=lead_time_hours):
        return "Requested time is inside booking lead-time window."

    max_advance_booking_days = get_max_advance_booking_days()
    if max_advance_booking_days > 0 and requested_datetime > now + timedelta(days=max_advance_booking_days):
        return "Requested time exceeds maximum advance booking window."

    return None


def get_slot_datetime(slot_time, reference_time=None):
    normalized_time = normalize_time_value(slot_time)
    if normalized_time is None or ":" not in normalized_time:
        return None

    reference_datetime = parse_requested_datetime(reference_time) if reference_time else get_business_now()
    if reference_datetime is None:
        reference_datetime = get_business_now()

    try:
        hour, minute = map(int, normalized_time.split(":"))
    except (TypeError, ValueError):
        return None

    candidate = reference_datetime.astimezone(get_business_timezone()).replace(
        hour=hour, minute=minute, second=0, microsecond=0,
    )
    if datetime.fromtimestamp(candidate.timestamp(), get_business_timezone()).replace(tzinfo=None) != candidate.replace(tzinfo=None):
        return None
    return candidate


def slot_passes_booking_window(slot_time, reference_time=None):
    slot_datetime = get_slot_datetime(slot_time, reference_time)
    if slot_datetime is None:
        return False
    return get_booking_window_message_for_datetime(slot_datetime) is None


def normalize_time_value(value):
    if value is None:
        return None

    time_value = str(value).strip()
    if not time_value:
        return None

    if time_value.lower() in {"null", "none", "string"}:
        return None

    if "T" in time_value:
        time_value = time_value.split("T", 1)[1]

    parts = time_value.split(":")
    if len(parts) < 2:
        return time_value

    return f"{parts[0]}:{parts[1]}"


def time_to_minutes(time_string: str):
    normalized_time = normalize_time_value(time_string)
    if normalized_time is None:
        raise ValueError("Invalid time value")
    if ":" not in normalized_time:
        raise ValueError("Invalid time value")

    hour, minute = map(int, normalized_time.split(":"))
    return hour * 60 + minute


def minutes_to_time(total_minutes: int):
    hour = total_minutes // 60
    minute = total_minutes % 60
    return f"{hour:02d}:{minute:02d}"


def format_display_time(time_string):
    try:
        normalized_time = normalize_time_value(time_string)
        hour, minute = map(int, normalized_time.split(":"))
        period = "AM" if hour < 12 else "PM"
        display_hour = hour % 12
        if display_hour == 0:
            display_hour = 12
        return f"{display_hour}:{minute:02d} {period}"
    except (AttributeError, TypeError, ValueError):
        return time_string


def add_minutes(time_string: str, minutes: int):
    return minutes_to_time(time_to_minutes(time_string) + minutes)


def generate_time_slots():
    slots = []
    start_minutes = time_to_minutes(get_business_setting('opening'))
    end_minutes = time_to_minutes(get_business_setting('closing')) - 1
    current = start_minutes
    while current <= end_minutes:
        slots.append(minutes_to_time(current))
        current += get_business_setting('interval_minutes')
    return slots


def time_fits(start_time: str, duration_minutes: int):
    start_minutes = time_to_minutes(start_time)
    return (
        time_to_minutes(get_business_setting('opening')) <= start_minutes
        and (start_minutes - time_to_minutes(get_business_setting('opening'))) % get_business_setting('interval_minutes') == 0
        and type(duration_minutes) is int and duration_minutes > 0
        and start_minutes + duration_minutes <= time_to_minutes(get_business_setting('closing'))
    )


def times_overlap(start_a: str, duration_a: int, start_b: str, duration_b: int):
    start_a = normalize_time_value(start_a)
    start_b = normalize_time_value(start_b)
    if start_a is None or start_b is None:
        return False

    try:
        start_a_minutes = time_to_minutes(start_a)
        end_a_minutes = start_a_minutes + duration_a
        start_b_minutes = time_to_minutes(start_b)
        end_b_minutes = start_b_minutes + duration_b
    except (TypeError, ValueError):
        return False

    return start_a_minutes < end_b_minutes and end_a_minutes > start_b_minutes


def get_active_bookings(reference_time=None, connection=None, exclude_id=None):
    try:
        with (nullcontext(connection) if connection is not None else closing(get_db_connection())) as conn, closing(conn.cursor()) as cursor:
            cursor.execute("""
            SELECT scheduled_at, duration_minutes
            FROM intake_requests
            WHERE tenant_id = %s
              AND (%s IS NULL OR id <> %s)
              AND appointment_status IN ('scheduled', 'pending', 'needs_confirmation', 'confirmed')
        """, (companies.tenant_id(), exclude_id, exclude_id))
            rows = cursor.fetchall()
        bookings = []
        for row in rows:
            if not isinstance(row, (tuple, list)) or len(row) != 2:
                raise SchedulingDataError()
            scheduled_at, duration_minutes = row
            if not isinstance(scheduled_at, datetime) or scheduled_at.tzinfo is None or scheduled_at.utcoffset() is None:
                raise SchedulingDataError()
            scheduled_at = scheduled_at.astimezone(timezone.utc)
            if type(duration_minutes) is not int or duration_minutes <= 0:
                raise SchedulingDataError()
            bookings.append((scheduled_at, duration_minutes))
        return bookings
    except SchedulingDataError:
        raise
    except Exception:
        raise SchedulingDataError() from None


def is_slot_available(start_time: str, duration_minutes: int, reference_time=None, connection=None, exclude_id=None):
    if not time_fits(start_time, duration_minutes):
        return False

    requested_start = get_slot_datetime(start_time, reference_time)
    if requested_start is None:
        return False
    requested_start = requested_start.astimezone(timezone.utc)
    requested_end = requested_start + timedelta(minutes=duration_minutes)
    for booking_start, booking_duration in get_active_bookings(reference_time, connection, exclude_id):
        booking_end = booking_start + timedelta(minutes=booking_duration)
        if requested_start < booking_end and booking_start < requested_end:
            return False
    return True


def find_next_available_slot(duration_minutes: int, preferred_time: Optional[str] = None):
    slots = generate_time_slots()

    if preferred_time:
        raw_preferred_time = preferred_time
        preferred_time = parse_requested_datetime(preferred_time).strftime("%H:%M")
        if (
            preferred_time in slots
            and slot_passes_booking_window(preferred_time, raw_preferred_time)
            and is_slot_available(preferred_time, duration_minutes, raw_preferred_time)
        ):
            return preferred_time
        preferred_minutes = time_to_minutes(preferred_time)
        for slot in slots:
            if (
                time_to_minutes(slot) > preferred_minutes
                and slot_passes_booking_window(slot, raw_preferred_time)
                and is_slot_available(slot, duration_minutes, raw_preferred_time)
            ):
                return slot
        return None

    for slot in slots:
        if slot_passes_booking_window(slot) and is_slot_available(slot, duration_minutes):
            return slot

    return None


def find_available_options(duration_minutes: int, preferred_time: Optional[str] = None, limit: int = 3):
    slots = generate_time_slots()
    options = []

    if preferred_time:
        raw_preferred_time = preferred_time
        preferred_time = parse_requested_datetime(preferred_time).strftime("%H:%M")
        preferred_minutes = time_to_minutes(preferred_time)

        for slot in slots:
            try:
                if (
                    time_to_minutes(slot) >= preferred_minutes
                    and slot_passes_booking_window(slot, raw_preferred_time)
                    and is_slot_available(slot, duration_minutes, raw_preferred_time)
                ):
                    options.append({
                        "time": slot,
                        "display": format_display_time(slot)
                    })
            except SchedulingDataError:
                raise
            except (TypeError, ValueError):
                continue
            if len(options) >= limit:
                break
        return options

    for slot in slots:
        if slot_passes_booking_window(slot) and is_slot_available(slot, duration_minutes):
            options.append({
                "time": slot,
                "display": format_display_time(slot)
            })
        if len(options) >= limit:
            break

    return options


def detect_service(reason: str):
    normalized = (reason or '').strip().lower()
    services = get_business_setting('services')
    if normalized in services:
        return normalized
    matched = [name for name, service in services.items()
               if any(keyword in normalized for keyword in service['keywords'])]
    if len(matched) != 1:
        raise HTTPException(422, 'Invalid service')
    return matched[0]


def get_db_connection():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set")

    try:
        conn = psycopg2.connect(database_url)
        return conn
    except Exception:
        print("Database connection failed")
        raise


def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                tenant_id TEXT PRIMARY KEY CHECK (tenant_id ~ '^[a-z][a-z0-9-]{0,62}$'),
                configuration JSONB NOT NULL,
                credential_digest TEXT NOT NULL UNIQUE CHECK (length(credential_digest)=64)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS intake_requests (
                id SERIAL PRIMARY KEY,
                tenant_id TEXT NOT NULL REFERENCES companies(tenant_id),
                scheduled_at TIMESTAMPTZ NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT,
                reason TEXT NOT NULL,
                preferred_time TEXT,
                source TEXT DEFAULT 'form',
                scheduled_time TEXT,
                appointment_status TEXT NOT NULL,
                service_type TEXT,
                industry TEXT,
                duration_minutes INTEGER,
                priority TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("ALTER TABLE intake_requests ADD COLUMN IF NOT EXISTS service_type TEXT")
        cursor.execute("ALTER TABLE intake_requests ADD COLUMN IF NOT EXISTS industry TEXT")
        cursor.execute("ALTER TABLE intake_requests ADD COLUMN IF NOT EXISTS duration_minutes INTEGER")
        cursor.execute("ALTER TABLE intake_requests ADD COLUMN IF NOT EXISTS priority TEXT")
        cursor.execute("ALTER TABLE intake_requests ADD COLUMN IF NOT EXISTS tenant_id TEXT REFERENCES companies(tenant_id)")
        cursor.execute("ALTER TABLE intake_requests ALTER COLUMN tenant_id SET NOT NULL")
        cursor.execute("ALTER TABLE intake_requests ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMPTZ")
        cursor.execute("ALTER TABLE intake_requests ALTER COLUMN scheduled_at SET NOT NULL")
        cursor.execute("CREATE INDEX IF NOT EXISTS intake_requests_tenant_idx ON intake_requests(tenant_id)")
        conn.commit()
        cursor.close()
        conn.close()
    except Exception:
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        raise RuntimeError('Database initialization failed') from None


@app.exception_handler(RequestValidationError)
async def invalid_request_handler(request, exc):
    return JSONResponse(status_code=422, content={'detail': 'Invalid request'})


def record_from_tuple(row):
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "phone": row[2],
        "email": row[3],
        "reason": row[4],
        "preferred_time": row[5],
        "source": row[6],
        "scheduled_time": row[7],
        "appointment_status": row[8],
        "service_type": row[9],
        "industry": row[10],
        "duration_minutes": row[11],
        "priority": row[12],
        "created_at": str(row[13]) if row[13] else None,
    }


def fetch_intakes_by_field(field_name, value):
    if field_name not in ALLOWED_INTAKE_FILTER_FIELDS:
        raise ValueError("Invalid intake filter field")

    with closing(get_db_connection()) as conn, closing(conn.cursor()) as cursor:
        cursor.execute(f"""
            SELECT id, name, phone, email, reason, preferred_time, source, scheduled_time, appointment_status, service_type, industry, duration_minutes, priority, created_at
            FROM intake_requests
            WHERE tenant_id = %s AND {field_name} = %s
            ORDER BY created_at DESC
        """, (companies.tenant_id(), value))
        rows = cursor.fetchall()


    return [record_from_tuple(row) for row in rows]


def require_admin_auth(authorization: Optional[str] = Header(None)):
    expected_token = os.getenv("ADMIN_API_TOKEN")
    if not expected_token:
        raise HTTPException(status_code=500, detail="Internal server error")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.replace("Bearer ", "", 1).strip()
    try:
        token_matches = secrets.compare_digest(token, expected_token)
    except TypeError:
        # String comparison rejects non-ASCII text; treat it as invalid credentials.
        token_matches = False
    if not token_matches:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True




@app.get("/")
def root():
    return {
        "message": "Receptionist Core is running",
        "status": "ok",
        "version": "0.1.0"
    }


@app.get("/health")
def health_check():
    return {
        "ok": True,
        "service": "receptionist-core"
    }


@app.get("/settings")
def get_settings(admin_auth: bool = Depends(companies.require_tenant)):
    return {
        "status": "ok",
        "settings": companies.current()["configuration"],
    }


@app.get("/dashboard/stats")
def dashboard_stats(admin_auth: bool = Depends(companies.require_tenant)):
    try:
        with closing(get_db_connection()) as conn, closing(conn.cursor()) as cursor:

            cursor.execute("SELECT COUNT(*) FROM intake_requests WHERE tenant_id = %s", (companies.tenant_id(),))
            total_intakes = cursor.fetchone()[0]

            by_status = {
                status: 0
                for status in VALID_APPOINTMENT_STATUSES
            }
            cursor.execute("""
                SELECT appointment_status, COUNT(*)
                FROM intake_requests
                WHERE tenant_id = %s
                GROUP BY appointment_status
            """, (companies.tenant_id(),))
            for status, count in cursor.fetchall():
                if status in by_status:
                    by_status[status] = count

            cursor.execute("""
                SELECT service_type, COUNT(*)
                FROM intake_requests
                WHERE tenant_id = %s AND service_type IS NOT NULL
                GROUP BY service_type
            """, (companies.tenant_id(),))
            by_service_type = {
                service_type: count
                for service_type, count in cursor.fetchall()
            }

            cursor.execute("""
                SELECT priority, COUNT(*)
                FROM intake_requests
                WHERE tenant_id = %s AND priority IS NOT NULL
                GROUP BY priority
            """, (companies.tenant_id(),))
            by_priority = {
                priority: count
                for priority, count in cursor.fetchall()
            }



        return {
            "status": "ok",
            "total_intakes": total_intakes,
            "by_status": by_status,
            "by_service_type": by_service_type,
            "by_priority": by_priority,
        }
    except Exception:
        return {
            "status": "error",
            "message": "Failed to fetch dashboard stats",
        }


@app.get("/admin/dashboard/demo", response_class=HTMLResponse)
def admin_dashboard_demo():
    return """
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Receptionist Core Admin Dashboard</title>
        <style>
            :root {
                color-scheme: light;
                --background: #f6f8fb;
                --surface: #ffffff;
                --surface-muted: #eef3f8;
                --border: #dbe3ec;
                --text: #172033;
                --muted: #637083;
                --accent: #2563eb;
                --accent-soft: #dbeafe;
                --success: #0f766e;
                --warning: #b45309;
                --danger: #be123c;
                --shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
            }

            * {
                box-sizing: border-box;
            }

            body {
                margin: 0;
                background: var(--background);
                color: var(--text);
                font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                line-height: 1.5;
            }

            .page {
                width: min(1180px, calc(100% - 40px));
                margin: 0 auto;
                padding: 42px 0 28px;
            }

            header {
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: 24px;
                margin-bottom: 28px;
            }

            .eyebrow {
                margin: 0 0 8px;
                color: var(--accent);
                font-size: 0.78rem;
                font-weight: 800;
                letter-spacing: 0;
                text-transform: uppercase;
            }

            h1 {
                margin: 0;
                font-size: clamp(2rem, 4vw, 3.15rem);
                line-height: 1.05;
                letter-spacing: 0;
            }

            .subtitle {
                max-width: 640px;
                margin: 12px 0 0;
                color: var(--muted);
                font-size: 1rem;
            }

            .status-pill {
                flex: 0 0 auto;
                margin-top: 4px;
                border: 1px solid var(--border);
                border-radius: 999px;
                background: var(--surface);
                color: var(--success);
                padding: 10px 14px;
                font-size: 0.88rem;
                font-weight: 700;
                box-shadow: 0 8px 22px rgba(15, 23, 42, 0.05);
            }

            .metrics-grid {
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: 16px;
                margin-bottom: 18px;
            }

            .card {
                border: 1px solid var(--border);
                border-radius: 18px;
                background: var(--surface);
                box-shadow: var(--shadow);
            }

            .metric {
                padding: 22px;
                min-height: 132px;
            }

            .metric-label {
                margin: 0;
                color: var(--muted);
                font-size: 0.86rem;
                font-weight: 700;
            }

            .metric-value {
                margin: 12px 0 4px;
                font-size: 2.55rem;
                font-weight: 800;
                line-height: 1;
            }

            .metric-note {
                margin: 0;
                color: var(--muted);
                font-size: 0.84rem;
            }

            .total-card {
                grid-column: span 2;
                background: linear-gradient(135deg, #ffffff 0%, #eef6ff 100%);
            }

            .content-grid {
                display: grid;
                grid-template-columns: 1.2fr 0.8fr;
                gap: 18px;
            }

            .panel {
                padding: 24px;
            }

            .panel-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 16px;
                margin-bottom: 18px;
            }

            h2 {
                margin: 0;
                font-size: 1.1rem;
                letter-spacing: 0;
            }

            .panel-kicker {
                margin: 0;
                color: var(--muted);
                font-size: 0.86rem;
                font-weight: 700;
            }

            .list {
                display: grid;
                gap: 12px;
            }

            .row {
                display: grid;
                grid-template-columns: minmax(120px, 1fr) auto;
                align-items: center;
                gap: 14px;
            }

            .row-label {
                color: var(--text);
                font-weight: 700;
            }

            .row-value {
                color: var(--text);
                font-weight: 800;
            }

            .bar {
                grid-column: 1 / -1;
                height: 9px;
                overflow: hidden;
                border-radius: 999px;
                background: var(--surface-muted);
            }

            .bar span {
                display: block;
                height: 100%;
                border-radius: inherit;
                background: var(--accent);
            }

            .bar .success {
                background: var(--success);
            }

            .bar .warning {
                background: var(--warning);
            }

            .bar .danger {
                background: var(--danger);
            }

            footer {
                margin-top: 26px;
                color: var(--muted);
                font-size: 0.9rem;
                text-align: center;
            }

            @media (max-width: 880px) {
                header,
                .content-grid {
                    grid-template-columns: 1fr;
                }

                header {
                    display: block;
                }

                .status-pill {
                    display: inline-flex;
                    margin-top: 18px;
                }

                .metrics-grid {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }
            }

            @media (max-width: 560px) {
                .page {
                    width: min(100% - 28px, 1180px);
                    padding-top: 28px;
                }

                .metrics-grid {
                    grid-template-columns: 1fr;
                }

                .total-card {
                    grid-column: span 1;
                }

                .metric,
                .panel {
                    padding: 18px;
                }
            }
        </style>
    </head>
    <body>
        <main class="page">
            <header>
                <div>
                    <p class="eyebrow">Demo Admin</p>
                    <h1>Receptionist Core Admin Dashboard</h1>
                    <p class="subtitle">Portfolio-ready operational snapshot using hardcoded sample data for intake, scheduling, and workflow visibility.</p>
                </div>
                <div class="status-pill">Demo data only</div>
            </header>

            <section class="metrics-grid" aria-label="Dashboard totals">
                <article class="card metric total-card">
                    <p class="metric-label">Total Intakes</p>
                    <p class="metric-value">12</p>
                    <p class="metric-note">Sample requests across active workflows</p>
                </article>
                <article class="card metric">
                    <p class="metric-label">Scheduled</p>
                    <p class="metric-value">5</p>
                    <p class="metric-note">Appointments assigned</p>
                </article>
                <article class="card metric">
                    <p class="metric-label">Confirmed</p>
                    <p class="metric-value">3</p>
                    <p class="metric-note">Clients confirmed</p>
                </article>
                <article class="card metric">
                    <p class="metric-label">Checked In</p>
                    <p class="metric-value">1</p>
                    <p class="metric-note">Currently active</p>
                </article>
                <article class="card metric">
                    <p class="metric-label">Completed</p>
                    <p class="metric-value">2</p>
                    <p class="metric-note">Finished visits</p>
                </article>
                <article class="card metric">
                    <p class="metric-label">Cancelled</p>
                    <p class="metric-value">1</p>
                    <p class="metric-note">Removed from flow</p>
                </article>
                <article class="card metric">
                    <p class="metric-label">No Show</p>
                    <p class="metric-value">0</p>
                    <p class="metric-note">Missed appointments</p>
                </article>
            </section>

            <section class="content-grid">
                <article class="card panel">
                    <div class="panel-header">
                        <h2>Service Breakdown</h2>
                        <p class="panel-kicker">12 total</p>
                    </div>
                    <div class="list">
                        <div class="row">
                            <span class="row-label">Haircut</span>
                            <span class="row-value">4</span>
                            <div class="bar"><span style="width: 100%;"></span></div>
                        </div>
                        <div class="row">
                            <span class="row-label">Coloring</span>
                            <span class="row-value">3</span>
                            <div class="bar"><span style="width: 75%;"></span></div>
                        </div>
                        <div class="row">
                            <span class="row-label">Full Set Lashes</span>
                            <span class="row-value">2</span>
                            <div class="bar"><span style="width: 50%;"></span></div>
                        </div>
                        <div class="row">
                            <span class="row-label">Lash Fill</span>
                            <span class="row-value">2</span>
                            <div class="bar"><span style="width: 50%;"></span></div>
                        </div>
                        <div class="row">
                            <span class="row-label">Consultation</span>
                            <span class="row-value">1</span>
                            <div class="bar"><span style="width: 25%;"></span></div>
                        </div>
                    </div>
                </article>

                <article class="card panel">
                    <div class="panel-header">
                        <h2>Priority Breakdown</h2>
                        <p class="panel-kicker">Demo mix</p>
                    </div>
                    <div class="list">
                        <div class="row">
                            <span class="row-label">Normal</span>
                            <span class="row-value">10</span>
                            <div class="bar"><span class="success" style="width: 100%;"></span></div>
                        </div>
                        <div class="row">
                            <span class="row-label">Low</span>
                            <span class="row-value">2</span>
                            <div class="bar"><span class="warning" style="width: 20%;"></span></div>
                        </div>
                    </div>
                </article>
            </section>

            <footer>Receptionist Core - Modular intake, scheduling, and workflow engine</footer>
        </main>
    </body>
    </html>
    """


@app.post("/intake", dependencies=[Depends(companies.require_tenant)])
def create_intake(request: IntakeRequest):
    service_type = detect_service(request.reason)
    service = get_business_setting('services')[service_type]
    duration_minutes = service["duration_minutes"]

    if not is_valid_preferred_time(request.preferred_time):
        return invalid_preferred_time_response(service_type, service)

    requested_at = parse_requested_datetime(request.preferred_time)
    if requested_at is not None and (requested_at.second or requested_at.microsecond):
        return invalid_preferred_time_response(service_type, service)
    preferred_time = requested_at.strftime("%H:%M") if requested_at else None

    if preferred_time is None:
        options = find_available_options(duration_minutes)
        return {
            "status": "needs_selection",
            "service_type": service_type,
            "industry": service["industry"],
            "duration_minutes": service["duration_minutes"],
            "priority": service["priority"],
            "available_options": options,
        }

    booking_window_message = get_booking_window_message(request.preferred_time)
    if booking_window_message:
        if booking_window_message == "Requested time exceeds maximum advance booking window.":
            options = []
        else:
            try:
                options = find_available_options(duration_minutes, request.preferred_time)
            except (TypeError, ValueError):
                options = find_available_options(duration_minutes)
        return {
            "status": "slot_unavailable",
            "service_type": service_type,
            "industry": service["industry"],
            "duration_minutes": service["duration_minutes"],
            "priority": service["priority"],
            "available_options": options,
            "message": booking_window_message,
        }

    try:
        preferred_time_available = is_slot_available(preferred_time, duration_minutes, request.preferred_time)
    except (TypeError, ValueError):
        preferred_time_available = False

    if not preferred_time_available:
        try:
            options = find_available_options(duration_minutes, request.preferred_time)
        except (TypeError, ValueError):
            options = find_available_options(duration_minutes)
        return {
            "status": "slot_unavailable",
            "service_type": service_type,
            "industry": service["industry"],
            "duration_minutes": service["duration_minutes"],
            "priority": service["priority"],
            "available_options": options,
        }

    scheduled_time = requested_at.isoformat()
    appointment_status = determine_initial_appointment_status() if scheduled_time else "pending"

    try:
        with closing(get_db_connection()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute("SET LOCAL lock_timeout = '10s'")
            cursor.execute("SELECT tenant_id FROM companies WHERE tenant_id = %s FOR UPDATE", (companies.tenant_id(),))
            if cursor.fetchone() is None:
                raise SchedulingDataError()
            if not is_slot_available(preferred_time, duration_minutes, scheduled_time, conn):
                conn.rollback()
                return {'status': 'slot_unavailable', 'service_type': service_type,
                        'industry': service['industry'], 'duration_minutes': duration_minutes,
                        'priority': service['priority'], 'available_options': []}
            cursor.execute("""
                INSERT INTO intake_requests
                (name, phone, email, reason, preferred_time, source, scheduled_time, appointment_status, service_type, industry, duration_minutes, priority, tenant_id, scheduled_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, name, phone, email, reason, preferred_time, source, scheduled_time, appointment_status, service_type, industry, duration_minutes, priority, created_at
            """, (request.name, request.phone, request.email, request.reason, scheduled_time,
                  request.source, scheduled_time, appointment_status, service_type, service["industry"], service["duration_minutes"], service["priority"], companies.tenant_id(), requested_at))
            row = cursor.fetchone()
            conn.commit()

        
        record = record_from_tuple(row)

        if scheduled_time is None:
            status = "no_availability"
            scheduling_note = "no_availability"
        elif preferred_time:
            if requested_at is not None:
                status = appointment_status
                scheduling_note = "preferred_time_confirmed"
            else:
                status = appointment_status
                scheduling_note = "preferred_time_unavailable_next_slot_assigned"
        else:
            status = appointment_status
            scheduling_note = "next_available_assigned"

        return {
            "status": status,
            "service_type": service_type,
            "industry": service["industry"],
            "duration_minutes": service["duration_minutes"],
            "priority": service["priority"],
            "scheduled_time": scheduled_time,
            "scheduling_note": scheduling_note,
            "notification_decision": build_notification_decision(),
            "deposit_decision": build_deposit_decision(),
            "data": record,
        }
    except SchedulingDataError:
        raise
    except Exception:
        return {
            "status": "error",
            "service_type": service_type,
            "industry": service["industry"],
            "duration_minutes": service["duration_minutes"],
            "priority": service["priority"],
            "message": "Failed to create intake",
        }


@app.post("/availability", dependencies=[Depends(companies.require_tenant)])
def get_availability(request: AvailabilityRequest):
    service_type = detect_service(request.reason)
    service = get_business_setting('services')[service_type]

    if not is_valid_preferred_time(request.preferred_time):
        return invalid_preferred_time_response(service_type, service)

    booking_window_message = get_booking_window_message(request.preferred_time)
    if booking_window_message:
        return {
            "status": "no_availability",
            "service_type": service_type,
            "industry": service["industry"],
            "duration_minutes": service["duration_minutes"],
            "priority": service["priority"],
            "available_options": [],
            "message": booking_window_message,
        }

    options = find_available_options(
        service["duration_minutes"],
        request.preferred_time
    )

    if not options:
        return {
            "status": "no_availability",
            "service_type": service_type,
            "industry": service["industry"],
            "duration_minutes": service["duration_minutes"],
            "priority": service["priority"],
            "available_options": []
        }

    return {
        "status": "ok",
        "service_type": service_type,
        "industry": service["industry"],
        "duration_minutes": service["duration_minutes"],
        "priority": service["priority"],
        "available_options": options,
    }


@app.get("/intakes")
def list_intakes(admin_auth: bool = Depends(companies.require_tenant)):
    try:
        with closing(get_db_connection()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute("""
                SELECT id, name, phone, email, reason, preferred_time, source, scheduled_time, appointment_status, service_type, industry, duration_minutes, priority, created_at
                FROM intake_requests
                WHERE tenant_id = %s
                ORDER BY created_at DESC
            """, (companies.tenant_id(),))
            rows = cursor.fetchall()

        
        records = [record_from_tuple(row) for row in rows]
        return {
            "status": "ok",
            "count": len(records),
            "data": records,
        }
    except Exception:
        return {
            "status": "error",
            "message": "Failed to fetch intakes",
        }


@app.get("/intakes/status/{status}")
def list_intakes_by_status(status: str, admin_auth: bool = Depends(companies.require_tenant)):
    if status not in VALID_APPOINTMENT_STATUSES:
        return {
            "status": "error",
            "message": "Invalid appointment status",
        }

    try:
        records = fetch_intakes_by_field("appointment_status", status)
        return {
            "status": "ok",
            "filter": "status",
            "value": status,
            "count": len(records),
            "data": records,
        }
    except Exception:
        return {
            "status": "error",
            "message": "Failed to fetch intakes",
        }


@app.get("/intakes/service/{service_type}")
def list_intakes_by_service(service_type: str, admin_auth: bool = Depends(companies.require_tenant)):
    try:
        records = fetch_intakes_by_field("service_type", service_type)
        return {
            "status": "ok",
            "filter": "service_type",
            "value": service_type,
            "count": len(records),
            "data": records,
        }
    except Exception:
        return {
            "status": "error",
            "message": "Failed to fetch intakes",
        }


@app.get("/intakes/priority/{priority}")
def list_intakes_by_priority(priority: str, admin_auth: bool = Depends(companies.require_tenant)):
    try:
        records = fetch_intakes_by_field("priority", priority)
        return {
            "status": "ok",
            "filter": "priority",
            "value": priority,
            "count": len(records),
            "data": records,
        }
    except Exception:
        return {
            "status": "error",
            "message": "Failed to fetch intakes",
        }


@app.get("/intakes/{request_id}")
def get_intake(request_id: int, admin_auth: bool = Depends(companies.require_tenant)):
    try:
        with closing(get_db_connection()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute("""
                SELECT id, name, phone, email, reason, preferred_time, source, scheduled_time, appointment_status, service_type, industry, duration_minutes, priority, created_at
                FROM intake_requests
                WHERE id = %s AND tenant_id = %s
            """, (request_id, companies.tenant_id()))
            row = cursor.fetchone()

        
        if row:
            record = record_from_tuple(row)
            return {
                "status": "ok",
                "data": record,
            }
        return {
            "status": "not_found",
            "message": "Intake request not found",
        }
    except Exception:
        return {
            "status": "error",
            "message": "Failed to fetch intake",
        }


def update_intake_status(request_id, status):
    with closing(get_db_connection()) as conn, closing(conn.cursor()) as cursor:
        cursor.execute("SET LOCAL lock_timeout = '10s'")
        cursor.execute("SELECT tenant_id FROM companies WHERE tenant_id=%s FOR UPDATE", (companies.tenant_id(),))
        if cursor.fetchone() is None:
            raise SchedulingDataError()
        cursor.execute("SELECT scheduled_at,duration_minutes FROM intake_requests WHERE id=%s AND tenant_id=%s", (request_id,companies.tenant_id()))
        existing = cursor.fetchone()
        if existing and status in ('scheduled','pending','needs_confirmation','confirmed'):
            requested = existing[0].astimezone(get_business_timezone())
            if not is_slot_available(requested.strftime('%H:%M'),existing[1],requested.isoformat(),conn,request_id):
                raise SchedulingConflict()
        cursor.execute("""
            UPDATE intake_requests
            SET appointment_status = %s
            WHERE id = %s AND tenant_id = %s
            RETURNING id, name, phone, email, reason, preferred_time, source, scheduled_time, appointment_status, service_type, industry, duration_minutes, priority, created_at
        """, (status, request_id, companies.tenant_id()))
        row = cursor.fetchone()
        conn.commit()


    return record_from_tuple(row)


def fetch_intake_by_id(request_id):
    with closing(get_db_connection()) as conn, closing(conn.cursor()) as cursor:
        cursor.execute("""
            SELECT id, name, phone, email, reason, preferred_time, source, scheduled_time, appointment_status, service_type, industry, duration_minutes, priority, created_at
            FROM intake_requests
            WHERE id = %s AND tenant_id = %s
        """, (request_id, companies.tenant_id()))
        row = cursor.fetchone()


    return record_from_tuple(row)


@app.put("/intakes/{request_id}/status")
def update_intake_status_endpoint(request_id: int, update: StatusUpdate, admin_auth: bool = Depends(companies.require_tenant)):
    if update.appointment_status not in VALID_APPOINTMENT_STATUSES:
        return {
            "status": "error",
            "message": "Invalid appointment status",
        }

    try:
        if update.appointment_status == "cancelled":
            current_record = fetch_intake_by_id(request_id)
            if not current_record:
                return {
                    "status": "not_found",
                    "message": "Intake request not found",
                }
            if not can_cancel_booking(current_record["scheduled_time"]):
                return {
                    "status": "error",
                    "message": "Cancellation window has passed",
                }

        record = update_intake_status(request_id, update.appointment_status)
        if record:
            return {
                "status": "ok",
                "message": "Appointment status updated",
                "notification_decision": build_notification_decision(),
                "data": record,
            }
        return {
            "status": "not_found",
            "message": "Intake request not found",
        }
    except SchedulingConflict:
        return {'status':'slot_unavailable','message':'Appointment slot unavailable'}
    except Exception:
        return {
            "status": "error",
            "message": "Failed to update intake status",
        }


@app.delete("/intakes/{request_id}")
def delete_intake(request_id: int, admin_auth: bool = Depends(companies.require_tenant)):
    try:
        with closing(get_db_connection()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute("""
                DELETE FROM intake_requests
                WHERE id = %s AND tenant_id = %s
                RETURNING id
            """, (request_id, companies.tenant_id()))
            row = cursor.fetchone()
            conn.commit()

        
        if row:
            return {
                "status": "deleted",
                "deleted_id": request_id,
                "message": "Intake request deleted",
            }
        return {
            "status": "not_found",
            "message": "Intake request not found",
        }
    except Exception:
        return {
            "status": "error",
            "message": "Failed to delete intake",
        }


@app.post('/platform/companies/{tenant_id}')
def provision_company(tenant_id: str, config: companies.CompanyConfig,
                      admin=Depends(require_admin_auth)):
    return companies.provision(tenant_id, config)


@app.put('/platform/companies/{tenant_id}')
def configure_company(tenant_id: str, config: companies.CompanyConfig,
                      admin=Depends(require_admin_auth)):
    return companies.configure(tenant_id, config)


@app.get('/companies/{tenant_id}')
def company_configuration(tenant_id: str, tenant=Depends(companies.require_tenant)):
    return tenant


@app.put('/companies/{tenant_id}')
def update_company_configuration(tenant_id: str, config: companies.CompanyConfig,
                                 tenant=Depends(companies.require_tenant)):
    if not config.active:
        raise HTTPException(403, 'Forbidden')
    return companies.configure(tenant['tenant_id'], config)
