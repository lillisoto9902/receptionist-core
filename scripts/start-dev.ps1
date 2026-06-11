$ErrorActionPreference = "Stop"

$envPath = Join-Path (Get-Location) ".env"

if (-not (Test-Path $envPath)) {
    Write-Host "Missing .env file. Copy .env.example to .env and fill in local values."
    exit 1
}

Get-Content $envPath | ForEach-Object {
    $line = $_.Trim()

    if (-not $line -or $line.StartsWith("#")) {
        return
    }

    $parts = $line.Split("=", 2)
    if ($parts.Count -ne 2) {
        return
    }

    $name = $parts[0].Trim()
    $value = $parts[1].Trim()

    if ($name) {
        Set-Item -Path "Env:$name" -Value $value
    }
}

if (-not $env:DATABASE_URL) {
    Write-Host "DATABASE_URL is not set. Add it to .env."
    exit 1
}
Write-Host "Loaded DATABASE_URL"

if (-not $env:ADMIN_API_TOKEN) {
    Write-Host "ADMIN_API_TOKEN is not set. Add it to .env."
    exit 1
}
Write-Host "Loaded ADMIN_API_TOKEN"

Write-Host "Starting Receptionist Core dev server..."
uvicorn app.main:app --reload
