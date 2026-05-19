# receptionist-core

Reusable FastAPI backend template for industry-specific receptionist bots. It provides intake, service classification, PostgreSQL-backed scheduling, availability lookup, and appointment status management.

## Purpose

Receptionist Core is the base backend for customized digital receptionist builds. The current template is salon-oriented, but the structure is intended to be cloned and adapted for other industries by changing service definitions, routing rules, and downstream integrations.

## Current Capabilities

- FastAPI application with health and debug endpoints
- PostgreSQL connection through `DATABASE_URL`
- Service detection from intake reason text
- Duration-aware scheduling
- Availability search with display-ready time options
- Intake confirmation flow that only books selected available slots
- Appointment list, detail, status update, and delete endpoints

## Setup

1. Create and activate a virtual environment.

```bash
python -m venv .venv
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

On macOS or Linux:

```bash
source .venv/bin/activate
```

2. Install dependencies.

```bash
pip install -r requirements.txt
```

3. Configure the required environment variable.

```bash
DATABASE_URL=postgresql://username:password@host:port/database?sslmode=require
```

You can copy `.env.example` as a starting point, but do not commit real credentials.

4. Run locally.

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`.

## Required Environment Variables

- `DATABASE_URL`: PostgreSQL connection string. Use SSL mode when required by the database provider.

## Endpoints

- `GET /`: basic service status
- `GET /health`: health check
- `GET /debug/database-url`: confirms whether `DATABASE_URL` is set and shows a short preview
- `POST /availability`: returns available appointment options for a requested service reason
- `POST /intake`: confirms and stores an intake only when a selected preferred time is available
- `GET /intakes`: lists intake records
- `GET /intakes/{request_id}`: fetches one intake record
- `PUT /intakes/{request_id}/status`: updates appointment status
- `DELETE /intakes/{request_id}`: deletes an intake record

## Current Limitations

- Scheduling is based on time-of-day only, not full calendar dates.
- Business hours and service definitions are hardcoded in `app/main.py`.
- Service detection is keyword-based.
- There is no authentication or authorization.
- There are no external calendar, SMS, or email integrations yet.
- Availability and booking are designed for a single shared schedule.

## Template Notes

This repository is intended to be cloned as a reusable core backend for industry-specific receptionist bots. Customize service definitions, detection logic, business rules, and integrations per client or vertical while keeping the core API structure stable.
