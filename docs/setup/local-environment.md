# Local Environment

## Purpose

This guide describes how to load local environment variables and start the Receptionist Core development server without committing credentials.

## Required Variables

- DATABASE_URL
- ADMIN_API_TOKEN

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

The startup script loads required variables from `.env`, validates that they are present, and starts Uvicorn.

## Security Rules

- Never commit `.env`.
- Never paste real credentials into docs.
- Store credentials in a password vault.
- Rotate credentials if exposed.
