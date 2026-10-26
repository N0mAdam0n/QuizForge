import asyncio
import hashlib
import hmac
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core.config import Settings
from app.services.telemetry import service as svc_mod
from app.services.telemetry.service import TelemetryService


def make_service(tmp_path, transport=None):
    configured = Settings(
        DATA_DIR=tmp_path,
        SECRET_KEY="test-secret-key",
        TELEMETRY_ENDPOINT="http://127.0.0.1:8000",
    )
    return TelemetryService(configured, transport=transport)


def queued(service):
    with sqlite3.connect(service.queue_path) as db:
        return [json.loads(r[0]) for r in db.execute("SELECT json FROM queue ORDER BY id")]


def age_queue(service, seconds):
    old = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    with sqlite3.connect(service.queue_path) as db:
        db.execute("UPDATE queue SET created_at = ?", (old,))


def ok_handler(log):
    async def handler(request: httpx.Request) -> httpx.Response:
        log.append((request.url.path, json.loads(request.content or b"null")))
        if request.url.path == "/v1/devices/register":
            return httpx.Response(201, json={"device_id": "d" * 32, "token": "tok"})
        return httpx.Response(202, json={"accepted": 1, "quarantined": False})
    return handler


@pytest.fixture
def fixed_guid(monkeypatch):
    monkeypatch.setattr(svc_mod, "_read_windows_machine_guid", lambda: "1234-abcd")
    return "1234-abcd"


def test_machine_hash_is_hmac_of_guid_and_stable_across_reinstalls(tmp_path, fixed_guid):
    a = make_service(tmp_path / "install1")
    b = make_service(tmp_path / "install2")
    a.set_consent(True)
    b.set_consent(True)
    expected = hmac.new(svc_mod._MACHINE_PEPPER, b"win:1234-abcd", hashlib.sha256).hexdigest()
    assert a.machine_hash() == b.machine_hash() == expected
    assert "1234-abcd" not in json.dumps(queued(a))
    assert "1234-abcd" not in (tmp_path / "install1" / "telemetry.json").read_text()


def test_machine_hash_requires_consent(tmp_path, fixed_guid):
    assert make_service(tmp_path).machine_hash() is None


def test_machine_hash_fallback_is_random_but_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(svc_mod, "_read_windows_machine_guid", lambda: None)
    s = make_service(tmp_path)
    s.set_consent(True)
    first = s.machine_hash()
    again = make_service(tmp_path)
    assert again.machine_hash() == first
    other = make_service(tmp_path / "other")
    other.set_consent(True)
    assert other.machine_hash() != first


def test_events_are_schema_v2_with_machine_hash(tmp_path, fixed_guid):
    s = make_service(tmp_path)
    s.set_consent(True)
    s.emit_practice_answer(question_id=1, question_type="single_choice", correct=True,
                           time_ms=1200, session_id="x")
    events = queued(s)
    assert events and all(e["schema_version"] == 2 for e in events)
    assert all(e["machine_hash"] == s.machine_hash() for e in events)


def test_flush_timing_by_count_and_age(tmp_path, fixed_guid):
    s = make_service(tmp_path)
    s.set_consent(True)  # queues one app_meta
    assert s.should_flush() is False
    assert 170 <= s._next_flush_delay() <= 180
    age_queue(s, 181)
    assert s.should_flush() is True
    assert s._next_flush_delay() == 1.0

    s2 = make_service(tmp_path / "b")
    s2.set_consent(True)
    for i in range(49):
        s2.emit({"event_type": "app_meta", "app_version": "1", "os": "windows"})
    assert s2._queue_size() == 50
    assert s2.should_flush() is True


@pytest.mark.asyncio
async def test_flush_now_registers_with_machine_hash_and_uploads(tmp_path, fixed_guid):
    log = []
    s = make_service(tmp_path, transport=httpx.MockTransport(ok_handler(log)))
    s.set_consent(True)
    result = await s.flush_now()
    assert result["ok"] is True and result["sent"] == 1 and result["pending"] == 0
    assert log[0][0] == "/v1/devices/register"
    assert log[0][1]["machine_hash"] == s.machine_hash()
    assert s.is_registered()
    st = s.status()
    assert st["registered"] and st["pending"] == 0 and st["last_upload"]["ok"]


@pytest.mark.asyncio
async def test_run_registers_immediately_after_consent_and_flushes_old_events(tmp_path, fixed_guid):
    log = []
    s = make_service(tmp_path, transport=httpx.MockTransport(ok_handler(log)))
    s.set_consent(True)
    age_queue(s, 200)
    task = asyncio.create_task(s.run())
    for _ in range(100):
        if s._queue_size() == 0 and s.is_registered():
            break
        await asyncio.sleep(0.02)
    s.stop()
    await asyncio.wait_for(task, 2)
    assert s.is_registered()
    assert [p for p, _ in log] == ["/v1/devices/register", "/v1/events"]


@pytest.mark.asyncio
async def test_run_does_not_send_fresh_small_queue_but_registers(tmp_path, fixed_guid):
    log = []
    s = make_service(tmp_path, transport=httpx.MockTransport(ok_handler(log)))
    s.set_consent(True)
    s._queue_size()  # fresh event, below batch size
    task = asyncio.create_task(s.run())
    for _ in range(100):
        if log:
            break
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.05)
    s.stop()
    await asyncio.wait_for(task, 2)
    # flush_now on registration sends the single queued event too, which is fine;
    # the key property is that registration happens without waiting for 50 events.
    assert log[0][0] == "/v1/devices/register"


@pytest.mark.asyncio
async def test_shutdown_flush_sends_pending(tmp_path, fixed_guid):
    log = []
    s = make_service(tmp_path, transport=httpx.MockTransport(ok_handler(log)))
    s.set_consent(True)
    await s.shutdown_flush(timeout=3)
    assert s._queue_size() == 0
    assert any(p == "/v1/events" for p, _ in log)


@pytest.mark.asyncio
async def test_shutdown_flush_respects_timeout_and_keeps_queue(tmp_path, fixed_guid):
    async def slow(request):
        await asyncio.sleep(10)
        return httpx.Response(500)

    s = make_service(tmp_path, transport=httpx.MockTransport(slow))
    s.set_consent(True)
    start = time.monotonic()
    await s.shutdown_flush(timeout=0.3)
    assert time.monotonic() - start < 2
    assert s._queue_size() == 1


@pytest.mark.asyncio
async def test_shutdown_flush_noop_without_consent(tmp_path):
    s = make_service(tmp_path)
    await s.shutdown_flush(timeout=0.1)
    assert not s.queue_path.exists()
