# Local Environment

## Purpose

This guide describes how to load local environment variables and start the Receptionist Core development server without committing credentials.

## Required Variables

- DATABASE_URL
- ADMIN_API_TOKEN
- RC_ENVIRONMENT (`local` for this launcher)
- RC_DATABASE_HOST, RC_DATABASE_PORT, RC_DATABASE_NAME, RC_DATABASE_USER

The local target is exclusively the approved PostgreSQL 18.4 test cluster on
127.0.0.1:55432. Supply its runtime credentials through protected local storage;
do not use the existing server on port 5432. Initialize the schema with the approved
migrator before startup. Blank example credentials deliberately fail validation.
See [the release-candidate operating contract](release-candidate-operations.md)
for exact validation, readiness, deployment gates, and recovery requirements.

## Create Local .env

Copy `.env.example` to `.env`:

```powershell
Copy-Item .env.example .env
```

Fill in `.env` with local development values from the team password vault.

## Run the Dev Server

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-dev.ps1
```

The startup script rejects unknown/duplicate entries, validates operational settings,
and starts local Uvicorn with lifespan checks and access logging disabled. Startup
checks database identity, least privilege and schema readiness; it does not create schema.

## Security Rules

- Never commit `.env`.
- Never paste real credentials into docs.
- Store credentials in a password vault.
- Rotate credentials if exposed.
