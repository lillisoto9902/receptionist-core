"""Fixed-target credentials and connection identity checks; no import-time I/O."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import unquote, urlsplit

import psycopg2


ROOT = Path(r"C:\Users\sotoa\AppData\Local\CodeLogicAI\ReceptionistCore\Postgres18Test")
DATA = ROOT / "data"
DATABASE = "receptionist_core_test"
APP_ROLE = "receptionist_core_test_app"
MIGRATOR_ROLE = "receptionist_core_test_migrator"


class SafetyError(RuntimeError):
    """A non-secret integration gate failure."""


def require(condition, message):
    if not condition:
        raise SafetyError(message)


def same_path(left, right):
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def windows_state(backend_pid=None):
    backend = "null" if backend_pid is None else str(int(backend_pid))
    command = """
$ErrorActionPreference='Stop'
$backendId=BACKEND
$backendProcess=if($null -ne $backendId){Get-CimInstance Win32_Process -Filter "ProcessId = $backendId"}
[pscustomobject]@{
 listeners=@(Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -in 5432,55432} | Sort-Object LocalPort,LocalAddress | Select-Object LocalAddress,LocalPort,OwningProcess)
 services=@(Get-CimInstance Win32_Service | Where-Object {$_.Name -match 'postgres' -or $_.PathName -like '*Postgres18Test*'} | Sort-Object Name | Select-Object Name,State,ProcessId,PathName)
 backend=if($backendProcess){$backendProcess | Select-Object ProcessId,ParentProcessId,ExecutablePath}else{$null}
} | ConvertTo-Json -Depth 5
""".replace("BACKEND", "$null" if backend == "null" else backend)
    try:
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=30,
        )
        require(result.returncode == 0, "Windows cluster identity inspection failed")
        return json.loads(result.stdout)
    except SafetyError:
        raise
    except Exception:
        raise SafetyError("Windows cluster identity inspection unavailable") from None


def query(connection, statement, parameters=None):
    try:
        with connection.cursor() as cursor:
            cursor.execute(statement, parameters)
            return cursor.fetchall() if cursor.description else None
    except psycopg2.Error:
        raise SafetyError("Integration SQL operation failed") from None


class Target:
    def __init__(self):
        stage = "Credential/configuration loading"
        try:
            require(os.environ.get("RUN_RECEPTIONIST_DB_INTEGRATION") == "1", "Integration opt-in required")
            require(os.name == "nt", "Approved cluster requires Windows identity verification")
            settings = {}
            for line in (ROOT / "secrets" / "database.env").read_text(encoding="utf-8").splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                key, value = line.split("=", 1)
                require(key not in settings, "Ambiguous credential configuration")
                settings[key] = value
            self.passfile = ROOT / "secrets" / "absent-integration-pgpass"
            require(not self.passfile.exists(), "Unexpected integration password fallback file")
            stage = "URL/target validation"
            require(settings.get("RECEPTIONIST_TEST_DATABASE_HOST") == "127.0.0.1", "Unexpected configured host")
            require(settings.get("RECEPTIONIST_TEST_DATABASE_PORT") == "55432", "Unexpected configured port")
            require(settings.get("RECEPTIONIST_TEST_DATABASE_NAME") == DATABASE, "Unexpected configured database")
            self.urls = {}
            self.passwords = {}
            for role, key in (
                (APP_ROLE, "RECEPTIONIST_TEST_DATABASE_URL"),
                (MIGRATOR_ROLE, "RECEPTIONIST_TEST_MIGRATOR_DATABASE_URL"),
            ):
                value = settings[key]
                parsed = urlsplit(value)
                require(
                    parsed.scheme == "postgresql" and parsed.hostname == "127.0.0.1"
                    and parsed.port == 55432 and parsed.path == "/" + DATABASE
                    and unquote(parsed.username or "") == role
                    and bool(parsed.password) and not parsed.query and not parsed.fragment
                    and value == value.strip(),
                    "Missing, ambiguous, or unapproved database URL target",
                )
                self.urls[role] = value
                self.passwords[role] = unquote(parsed.password)
        except Exception:
            raise SafetyError(f"{stage} failed") from None

    def connect(self, role):
        stage = "URL/target validation"
        connection = None
        try:
            require(role in (APP_ROLE, MIGRATOR_ROLE), "Unapproved connection role")
            # The caller must sanitize its environment. Reject inherited libpq
            # settings rather than letting service/options files affect a run.
            require(not any(key.upper().startswith("PG") for key in os.environ), "Inherited PostgreSQL environment")
            stage = "Connection/authentication"
            connection = psycopg2.connect(
                host="127.0.0.1", hostaddr="127.0.0.1", port=55432,
                dbname=DATABASE, user=role, password=self.passwords[role],
                passfile=str(self.passfile), connect_timeout=5,
                sslmode="disable", application_name="phase13b_integration",
            )
            stage = "SQL server-identity validation"
            connection.autocommit = True
            identity = query(connection, """
                SELECT current_setting('server_version_num'), current_database(), current_user,
                       host(inet_server_addr()), inet_server_port(), pg_backend_pid()
            """)[0]
            require(identity[:5] == ("180004", DATABASE, role, "127.0.0.1", 55432), "SQL target identity mismatch")
            stage = "Process/PID/listener validation"
            pid_lines = (DATA / "postmaster.pid").read_text().splitlines()
            postmaster_pid = int(pid_lines[0])
            require(same_path(pid_lines[1], DATA) and pid_lines[3] == "55432" and pid_lines[7].strip() == "ready", "Isolated PID-file identity mismatch")
            require((DATA / "PG_VERSION").read_text().strip() == "18", "Local cluster version mismatch")
            state = windows_state(identity[5])
            listeners = [item for item in state["listeners"] if item["LocalPort"] == 55432]
            require(bool(listeners) and all(item["LocalAddress"] in ("127.0.0.1", "::1") and item["OwningProcess"] == postmaster_pid for item in listeners), "Isolated listener mismatch")
            backend = state["backend"]
            require(backend and backend["ParentProcessId"] == postmaster_pid, "SQL backend does not belong to approved cluster")
            require(same_path(backend["ExecutablePath"], r"C:\Program Files\PostgreSQL\18\bin\postgres.exe"), "Unexpected SQL backend executable")
            # Sensitive SQL path settings belong to administrator preflight.
            # Here, bind the backend to the postmaster identified by its PID file.
            connection.autocommit = False
            return connection
        except Exception:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass  # Never replace the sanitized stage with cleanup details.
            raise SafetyError(f"{stage} failed") from None


async def asgi_post(app, path, payload):
    body = json.dumps(payload).encode()
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": b"", "root_path": "", "headers": [(b"content-type", b"application/json")],
        "server": ("test.invalid", 80), "client": ("127.0.0.1", 1),
    }
    sent = False
    messages = []

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Event().wait()

    async def send(message):
        messages.append(message)

    await asyncio.wait_for(app(scope, receive, send), timeout=45)
    start = next(message for message in messages if message["type"] == "http.response.start")
    response = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return start["status"], json.loads(response)
