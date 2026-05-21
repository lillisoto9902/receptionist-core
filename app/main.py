import os
import psycopg2
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional


app = FastAPI(
    title="Receptionist Core",
    description="A modular digital receptionist engine for intake, scheduling, and client communication.",
    version="0.1.0",
)


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
    start_minutes = 9 * 60
    end_minutes = 16 * 60 + 30
    current = start_minutes
    while current <= end_minutes:
        slots.append(minutes_to_time(current))
        current += 30
    return slots


def time_fits(start_time: str, duration_minutes: int):
    end_minutes = time_to_minutes(start_time) + duration_minutes
    return end_minutes <= 17 * 60


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


def get_active_bookings():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT scheduled_time, duration_minutes
            FROM intake_requests
            WHERE scheduled_time IS NOT NULL
              AND appointment_status IN ('scheduled', 'pending')
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        bookings = []
        for row in rows:
            scheduled_time = normalize_time_value(row[0])
            duration_minutes = row[1]
            if scheduled_time is None or duration_minutes is None:
                continue
            try:
                time_to_minutes(scheduled_time)
                duration_minutes = int(duration_minutes)
            except (TypeError, ValueError):
                continue
            bookings.append((scheduled_time, duration_minutes))
        return bookings
    except Exception:
        return []


def is_slot_available(start_time: str, duration_minutes: int):
    if not time_fits(start_time, duration_minutes):
        return False

    for booking_time, booking_duration in get_active_bookings():
        booking_time = normalize_time_value(booking_time)
        if booking_time is None:
            continue
        if times_overlap(start_time, duration_minutes, booking_time, booking_duration):
            return False
    return True


def find_next_available_slot(duration_minutes: int, preferred_time: Optional[str] = None):
    slots = generate_time_slots()

    if preferred_time:
        if preferred_time in slots and is_slot_available(preferred_time, duration_minutes):
            return preferred_time
        preferred_minutes = time_to_minutes(preferred_time)
        for slot in slots:
            if time_to_minutes(slot) > preferred_minutes and is_slot_available(slot, duration_minutes):
                return slot
        return None

    for slot in slots:
        if is_slot_available(slot, duration_minutes):
            return slot

    return None


def find_available_options(duration_minutes: int, preferred_time: Optional[str] = None, limit: int = 3):
    slots = generate_time_slots()
    options = []

    if preferred_time:
        preferred_time = normalize_time_value(preferred_time)
        preferred_minutes = time_to_minutes(preferred_time)

        for slot in slots:
            try:
                if time_to_minutes(slot) >= preferred_minutes and is_slot_available(slot, duration_minutes):
                    options.append({
                        "time": slot,
                        "display": format_display_time(slot)
                    })
            except:
                continue
            if len(options) >= limit:
                break
        return options

    for slot in slots:
        if is_slot_available(slot, duration_minutes):
            options.append({
                "time": slot,
                "display": format_display_time(slot)
            })
        if len(options) >= limit:
            break

    return options


def detect_service(reason: str):
    normalized = (reason or "").lower()
    if "lash" in normalized and "fill" in normalized:
        return "lash_fill"
    if "lash" in normalized:
        return "full_set_lashes"
    if any(keyword in normalized for keyword in ("color", "dye", "highlight")):
        return "coloring"
    if any(keyword in normalized for keyword in ("style", "blowout", "updo")):
        return "styling"
    if any(keyword in normalized for keyword in ("treatment", "deep condition", "keratin")):
        return "treatment"
    if any(keyword in normalized for keyword in ("cut", "trim", "haircut")):
        return "haircut"
    return "consultation"


def get_db_connection():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set")

    try:
        conn = psycopg2.connect(database_url)
        return conn
    except Exception as e:
        print(f"Database connection failed: {e}")
        raise


def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS intake_requests (
                id SERIAL PRIMARY KEY,
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
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Failed to initialize database: {e}")


@app.on_event("startup")
async def startup():
    init_db()


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

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT id, name, phone, email, reason, preferred_time, source, scheduled_time, appointment_status, service_type, industry, duration_minutes, priority, created_at
        FROM intake_requests
        WHERE {field_name} = %s
        ORDER BY created_at DESC
    """, (value,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [record_from_tuple(row) for row in rows]




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


@app.get("/debug/database-url")
def debug_database_url():
    database_url = os.getenv("DATABASE_URL")
    return {
        "database_url_set": bool(database_url),
        "database_url_preview": database_url[:25] if database_url else None,
    }


@app.post("/intake")
def create_intake(request: IntakeRequest):
    service_type = detect_service(request.reason)
    service = SERVICES.get(service_type, SERVICES["consultation"])
    preferred_time = normalize_time_value(request.preferred_time)
    duration_minutes = service["duration_minutes"]

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

    try:
        preferred_time_available = is_slot_available(preferred_time, duration_minutes)
    except (TypeError, ValueError):
        preferred_time_available = False

    if not preferred_time_available:
        try:
            options = find_available_options(duration_minutes, preferred_time)
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

    scheduled_time = preferred_time
    appointment_status = "scheduled" if scheduled_time else "pending"

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO intake_requests 
            (name, phone, email, reason, preferred_time, source, scheduled_time, appointment_status, service_type, industry, duration_minutes, priority)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, name, phone, email, reason, preferred_time, source, scheduled_time, appointment_status, service_type, industry, duration_minutes, priority, created_at
        """, (request.name, request.phone, request.email, request.reason, preferred_time, 
              request.source, scheduled_time, appointment_status, service_type, service["industry"], service["duration_minutes"], service["priority"]))
        row = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        
        record = record_from_tuple(row)

        if scheduled_time is None:
            status = "no_availability"
            scheduling_note = "no_availability"
        elif preferred_time:
            if scheduled_time == preferred_time:
                status = "scheduled"
                scheduling_note = "preferred_time_confirmed"
            else:
                status = "scheduled"
                scheduling_note = "preferred_time_unavailable_next_slot_assigned"
        else:
            status = "scheduled"
            scheduling_note = "next_available_assigned"

        return {
            "status": status,
            "service_type": service_type,
            "industry": service["industry"],
            "duration_minutes": service["duration_minutes"],
            "priority": service["priority"],
            "scheduled_time": scheduled_time,
            "scheduling_note": scheduling_note,
            "data": record,
        }
    except Exception as e:
        return {
            "status": "error",
            "service_type": service_type,
            "industry": service["industry"],
            "duration_minutes": service["duration_minutes"],
            "priority": service["priority"],
            "message": f"Failed to create intake: {str(e)}",
        }


@app.post("/availability")
def get_availability(request: AvailabilityRequest):
    service_type = detect_service(request.reason)
    service = SERVICES.get(service_type, SERVICES["consultation"])

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
def list_intakes():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, phone, email, reason, preferred_time, source, scheduled_time, appointment_status, service_type, industry, duration_minutes, priority, created_at
            FROM intake_requests
            ORDER BY created_at DESC
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        records = [record_from_tuple(row) for row in rows]
        return {
            "status": "ok",
            "count": len(records),
            "data": records,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to fetch intakes: {str(e)}",
        }


@app.get("/intakes/status/{status}")
def list_intakes_by_status(status: str):
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
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to fetch intakes: {str(e)}",
        }


@app.get("/intakes/service/{service_type}")
def list_intakes_by_service(service_type: str):
    try:
        records = fetch_intakes_by_field("service_type", service_type)
        return {
            "status": "ok",
            "filter": "service_type",
            "value": service_type,
            "count": len(records),
            "data": records,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to fetch intakes: {str(e)}",
        }


@app.get("/intakes/priority/{priority}")
def list_intakes_by_priority(priority: str):
    try:
        records = fetch_intakes_by_field("priority", priority)
        return {
            "status": "ok",
            "filter": "priority",
            "value": priority,
            "count": len(records),
            "data": records,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to fetch intakes: {str(e)}",
        }


@app.get("/intakes/{request_id}")
def get_intake(request_id: int):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, phone, email, reason, preferred_time, source, scheduled_time, appointment_status, service_type, industry, duration_minutes, priority, created_at
            FROM intake_requests
            WHERE id = %s
        """, (request_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        
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
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to fetch intake: {str(e)}",
        }


def update_intake_status(request_id, status):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE intake_requests
        SET appointment_status = %s
        WHERE id = %s
        RETURNING id, name, phone, email, reason, preferred_time, source, scheduled_time, appointment_status, service_type, industry, duration_minutes, priority, created_at
    """, (status, request_id))
    row = cursor.fetchone()
    conn.commit()
    cursor.close()
    conn.close()

    return record_from_tuple(row)


@app.put("/intakes/{request_id}/status")
def update_intake_status_endpoint(request_id: int, update: StatusUpdate):
    if update.appointment_status not in VALID_APPOINTMENT_STATUSES:
        return {
            "status": "error",
            "message": "Invalid appointment status",
        }

    try:
        record = update_intake_status(request_id, update.appointment_status)
        if record:
            return {
                "status": "ok",
                "message": "Appointment status updated",
                "data": record,
            }
        return {
            "status": "not_found",
            "message": "Intake request not found",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to update intake status: {str(e)}",
        }


@app.delete("/intakes/{request_id}")
def delete_intake(request_id: int):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM intake_requests
            WHERE id = %s
            RETURNING id
        """, (request_id,))
        row = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        
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
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to delete intake: {str(e)}",
        }
