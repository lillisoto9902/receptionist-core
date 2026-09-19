"""Direct ASGI tests using unittest; no HTTP client dependency or lifespan startup."""

import asyncio
import json
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch

from app import main, companies
from test_scheduling_unit import SchedulingFixture


async def asgi_request(method, path, payload=None, headers=(), timeout=5):
    body = json.dumps(payload).encode() if payload is not None else b""
    url = urlsplit(path)
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": url.path, "raw_path": url.path.encode(),
        "query_string": url.query.encode(), "root_path": "",
        "headers": [(b"content-type", b"application/json"), *headers],
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

    await asyncio.wait_for(main.app(scope, receive, send), timeout=timeout)
    start = next(m for m in messages if m["type"] == "http.response.start")
    response = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], json.loads(response), dict(start["headers"])


class SchedulingAPITests(SchedulingFixture):
    def request(self, path, preferred="09:00", reason="consultation"):
        payload = {"reason": reason, "preferred_time": preferred}
        if path == "/intake":
            payload.update(name="Synthetic", phone="000")
        return asyncio.run(asgi_request("POST", path, payload))

    def assert_unavailable(self, response):
        status, body, _ = response
        self.assertEqual(status, 503)
        self.assertEqual(body, {"detail": "Scheduling unavailable"})
        self.assert_no_write()

    def test_availability_lookup_failures_return_only_generic_503(self):
        for failure in ("connection", "query", "fetch", "row", "duration"):
            with self.subTest(failure=failure):
                sensitive = RuntimeError("SELECT synthetic customer credential host detail")
                self.db.side_effect = sensitive if failure == "connection" else None
                self.cursor.execute.side_effect = sensitive if failure == "query" else None
                self.cursor.fetchall.side_effect = sensitive if failure == "fetch" else None
                self.cursor.fetchall.return_value = {"row": [("broken", 30)], "duration": [("09:00", -1)]}.get(failure, [])
                self.assert_unavailable(self.request("/availability"))

    def test_intake_lookup_failures_never_insert_or_commit(self):
        for failure in ("connection", "query", "fetch", "row", "duration"):
            with self.subTest(failure=failure):
                sensitive = RuntimeError("synthetic password connection SQL customer detail")
                self.db.side_effect = sensitive if failure == "connection" else None
                self.cursor.execute.side_effect = sensitive if failure == "query" else None
                self.cursor.fetchall.side_effect = sensitive if failure == "fetch" else None
                self.cursor.fetchall.return_value = {"row": [("broken", 30)], "duration": [("09:00", 0)]}.get(failure, [])
                self.assert_unavailable(self.request("/intake"))

    def test_integrity_exception_text_never_leaks(self):
        with patch.object(main, "get_active_bookings", side_effect=main.SchedulingDataError("synthetic SQL password customer infrastructure")):
            for path in ("/availability", "/intake"):
                self.assert_unavailable(self.request(path))

    def test_availability_discards_partial_options(self):
        for preferred in (None, "09:00"):
            with self.subTest(preferred=preferred):
                with patch.object(main, "get_active_bookings", side_effect=[[], main.SchedulingDataError()]):
                    self.assert_unavailable(self.request("/availability", preferred))

    def test_intake_selection_failure_discards_partial_options(self):
        with patch.object(main, "get_active_bookings", side_effect=[[], main.SchedulingDataError()]):
            self.assert_unavailable(self.request("/intake", None))

    def test_failure_during_conflict_alternatives_returns_503(self):
        with patch.object(main, "get_active_bookings", side_effect=[[(self.now.replace(hour=9), 30)], [], main.SchedulingDataError()]):
            self.assert_unavailable(self.request("/intake"))

    def test_before_opening_is_rejected_without_insert(self):
        status, body, _ = self.request("/intake", "08:30")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "slot_unavailable")
        self.assertTrue(all(item["time"] >= "09:00" for item in body["available_options"]))
        self.assert_no_write()

    def test_off_grid_is_rejected_without_insert(self):
        status, body, _ = self.request("/intake", "09:15")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "slot_unavailable")
        self.assertNotIn("09:15", [item["time"] for item in body["available_options"]])
        self.assert_no_write()

    def test_after_closing_is_rejected_without_insert(self):
        status, body, _ = self.request("/intake", "16:30", "haircut")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "slot_unavailable")
        self.assertEqual(body["available_options"], [])
        self.assert_no_write()

    def test_valid_boundaries_available_and_intake_succeeds(self):
        for start, reason in (("09:00", "consultation"), ("16:30", "consultation"), ("16:00", "haircut")):
            with self.subTest(start=start, reason=reason):
                self.conn.commit.reset_mock()
                self.cursor.execute.reset_mock()
                status, body, _ = self.request("/availability", start, reason)
                self.assertEqual(status, 200)
                self.assertEqual(body["available_options"][0]["time"], start)
                status, body, _ = self.request("/intake", start, reason)
                self.assertEqual(status, 200)
                self.assertEqual(body["status"], "scheduled")
                self.assertEqual(body["scheduled_time"], "2030-01-02T" + start + ":00+00:00")
                insert = self.cursor.execute.call_args.args
                self.assertIn("VALUES (%s", insert[0])
                self.assertEqual(insert[1][7], "scheduled")
                self.conn.commit.assert_called_once()

    def test_empty_success_is_available_without_authentication(self):
        status, body, _ = self.request("/availability", None)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(len(body["available_options"]), 3)
        status, body, _ = self.request("/intake", None)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "needs_selection")
        self.assert_no_write()

    def test_protected_routes_require_tenant_auth(self):
        main.app.dependency_overrides.pop(companies.require_tenant)
        with patch.dict(main.os.environ, {"ADMIN_API_TOKEN": "synthetic-test-only"}, clear=True):
            for method, path, payload in (
                ("GET", "/settings", None), ("GET", "/dashboard/stats", None),
                ("GET", "/intakes", None), ("GET", "/intakes/1", None),
                ("GET", "/intakes/status/scheduled", None),
                ("GET", "/intakes/service/haircut", None),
                ("GET", "/intakes/priority/normal", None),
                ("PUT", "/intakes/1/status", {"appointment_status": "scheduled"}),
                ("DELETE", "/intakes/1", None),
            ):
                with self.subTest(path=path):
                    status, body, headers = asyncio.run(asgi_request(method, path, payload))
                    self.assertEqual(status, 401)
                    self.assertEqual(body, {"detail": "Unauthorized"})
                    self.assertEqual(headers[b"www-authenticate"], b"Bearer")
            status, body, _ = asyncio.run(asgi_request(
                "GET", "/settings", headers=[(b"authorization", b"Bearer synthetic-test-only")]
            ))
            self.assertEqual(status, 401)
        self.db.assert_not_called()

    def test_public_health_routes_remain_public(self):
        for path in ("/", "/health"):
            status, _, _ = asyncio.run(asgi_request("GET", path))
            self.assertEqual(status, 200)
        self.db.assert_not_called()


if __name__ == "__main__":
    unittest.main()
