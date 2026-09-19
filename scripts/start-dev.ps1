$ErrorActionPreference = "Stop"

$envPath = Join-Path (Get-Location) ".env"

if (-not (Test-Path $envPath)) {
    Write-Host "Missing .env file. Copy .env.example to .env and fill in local values."
    exit 1
}

$allowed = @('RC_ENVIRONMENT','RC_DATABASE_HOST','RC_DATABASE_PORT','RC_DATABASE_NAME','RC_DATABASE_USER','DATABASE_URL','ADMIN_API_TOKEN')
$seen = @{}
Get-Content $envPath | ForEach-Object {
    $line = $_.Trim()

    if (-not $line -or $line.StartsWith("#")) {
        return
    }

    $parts = $line.Split("=", 2)
    if ($parts.Count -ne 2) {
        throw 'Invalid environment entry.'
    }

    $name = $parts[0].Trim()
    $value = $parts[1].Trim()

    if ($name -notin $allowed -or $seen.ContainsKey($name)) { throw 'Unexpected or duplicate environment entry.' }
    $seen[$name] = $true
    Set-Item -Path "Env:$name" -Value $value
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

if ($env:RC_ENVIRONMENT -ne 'local') { throw 'Development launcher requires local mode.' }
python -B -c "from app.operations import load_settings; load_settings()"
if ($LASTEXITCODE -ne 0) { throw 'Operational configuration invalid.' }
Write-Host "Starting Receptionist Core dev server..."
uvicorn app.main:app --reload --host 127.0.0.1 --lifespan on --no-access-log --no-proxy-headers
