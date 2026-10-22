import json
import sqlite3

import httpx
import pytest

from app.core.config import Settings
from app.core.security import create_access_token
from app.models.user import User
from app.services.telemetry import telemetry
from app.services.telemetry.service import TelemetryService


def make_service(tmp_path, *, transport=None, endpoint="http://127.0.0.1:8000"):
    configured = Settings(
        DATA_DIR=tmp_path,
        SECRET_KEY="test-secret-key",
        TELEMETRY_ENDPOINT=endpoint,
    )
    return TelemetryService(configured, transport=transport)


def queued_events(service):
    with sqlite3.connect(service.queue_path) as db:
        rows = db.execute("SELECT json FROM queue ORDER BY id").fetchall()
    return [json.loads(row[0]) for row in rows]


def test_emit_without_consent_does_not_create_files(tmp_path):
    service = make_service(tmp_path)

    service.emit_app_meta()
    service.emit_review_edit(
        question_id=12,
        import_task_id=7,
        fields_changed=["answer"],
        accepted_unchanged=False,
        edit_category="answer_fix",
    )

    assert not service.consent_path.exists()
    assert not service.queue_path.exists()


def test_disabled_telemetry_never_creates_local_state(tmp_path):
    configured = Settings(
        DATA_DIR=tmp_path,
        SECRET_KEY="test-secret-key",
        TELEMETRY_ENABLED=False,
    )
    service = TelemetryService(configured)

    assert service.set_consent(True) is False
    service.emit_app_meta()
    service.emit_practice_answer(
        question_id=5,
        question_type="single_choice",
        correct=True,
        time_ms=100,
        session_id="session",
    )

    assert not service.consent_path.exists()
    assert not service.queue_path.exists()


def test_import_and_practice_events_hash_ids_and_never_queue_text(tmp_path):
    service = make_service(tmp_path)
    service.set_consent(True)
    service.emit_import_parse(
        task_id="task-123",
        doc_format="md",
        diagnostics={
            "chosen_strategy": "rule",
            "local_details": {
                "per_question": [0.9],
                "quality": 0.9,
                "coverage": 1.0,
                "raw_coverage": 1.0,
                "expected_count": 1,
                "extracted_count": 1,
                "combined": 0.935,
            },
            "ai_details": None,
            "ai_called": False,
            "threshold": 0.75,
            "latency_ms": 12,
            "questions": [{"content": "DO NOT UPLOAD", "q_type": "true_false"}],
        },
    )
    service.emit_practice_answer(
        question_id=12,
        question_type="true_false",
        correct=True,
        time_ms=1500,
        session_id="session-secret",
    )
    service.emit_practice_answer(
        question_id=12,
        question_type="true_false",
        correct=None,
        time_ms=2000,
        session_id="session-secret",
    )

    events = queued_events(service)
    import_event = next(event for event in events if event["event_type"] == "import_parse")
    practice_events = [event for event in events if event["event_type"] == "practice_answer"]
    assert len(import_event["doc_id_hash"]) == 64
    assert import_event["question_type"] == "true_false"
    assert import_event["chosen_strategy"] == "rule"
    assert "DO NOT UPLOAD" not in json.dumps(events)
    assert len(practice_events) == 1
    assert len(practice_events[0]["item_hash"]) == 64
    assert len(practice_events[0]["session_hash"]) == 64
    assert practice_events[0]["attempt_no"] == 1


def test_consent_queues_only_allowlisted_events_and_withdrawal_clears_them(tmp_path):
    service = make_service(tmp_path)
    service.set_consent(True)
    service.emit_review_edit(
        question_id=12,
        import_task_id=7,
        fields_changed=["answer"],
        accepted_unchanged=False,
        edit_category="answer_fix",
    )

    events = queued_events(service)
    assert [event["event_type"] for event in events] == ["app_meta", "review_edit"]
    review = events[1]
    assert review["question_ref_hash"] != "12"
    assert review["doc_id_hash"] != "7"
    assert "question text" not in json.dumps(events)

    service.set_consent(False)

    assert not service.consent_path.exists()
    assert service._queue_size() == 0


def test_non_loopback_http_endpoint_is_rejected(tmp_path):
    service = make_service(tmp_path, endpoint="http://example.com")

    with pytest.raises(ValueError, match="loopback"):
        import asyncio

        asyncio.run(service._ssl_context("http://example.com"))


@pytest.mark.asyncio
async def test_422_drops_rejected_batch_without_retry(tmp_path):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/devices/register":
            return httpx.Response(201, json={"device_id": "d" * 32, "token": "test-token"})
        return httpx.Response(422, json={"detail": "invalid event"})

    service = make_service(tmp_path, transport=httpx.MockTransport(handler))
    service.set_consent(True)
    batch = service._load_batch()

    async with await service._make_client() as client:
        result, delay = await service._send_rows(client, batch)

    assert result == "done"
    assert delay is None
    assert service._queue_size() == 0


@pytest.mark.asyncio
async def test_401_reregisters_once_and_retries_batch(tmp_path):
    event_attempts = 0
    registrations = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal event_attempts, registrations
        if request.url.path == "/v1/devices/register":
            registrations += 1
            return httpx.Response(
                201,
                json={"device_id": "d" * 32, "token": f"token-{registrations}"},
            )
        event_attempts += 1
        if event_attempts == 1:
            return httpx.Response(401, json={"detail": "invalid token"})
        return httpx.Response(202, json={"accepted": 1, "quarantined": False})

    service = make_service(tmp_path, transport=httpx.MockTransport(handler))
    service.set_consent(True)
    batch = service._load_batch()

    async with await service._make_client() as client:
        result, _delay = await service._send_rows(client, batch)

    assert result == "done"
    assert registrations == 2
    assert event_attempts == 2
    assert service._queue_size() == 0


@pytest.mark.asyncio
async def test_429_keeps_batch_and_returns_retry_after(tmp_path):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/devices/register":
            return httpx.Response(201, json={"device_id": "d" * 32, "token": "test-token"})
        return httpx.Response(
            429,
            headers={"Retry-After": "45"},
            json={"detail": "rate limited"},
        )

    service = make_service(tmp_path, transport=httpx.MockTransport(handler))
    service.set_consent(True)
    batch = service._load_batch()

    async with await service._make_client() as client:
        result, delay = await service._send_rows(client, batch)

    assert result == "retry"
    assert delay == 45
    assert service._queue_size() == 1


@pytest.mark.asyncio
async def test_offline_endpoint_keeps_events_queued(tmp_path):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/devices/register":
            return httpx.Response(201, json={"device_id": "d" * 32, "token": "test-token"})
        raise httpx.ConnectError("offline", request=request)

    service = make_service(tmp_path, transport=httpx.MockTransport(handler))
    service.set_consent(True)
    batch = service._load_batch()

    async with await service._make_client() as client:
        result, delay = await service._send_rows(client, batch)

    assert result == "retry"
    assert delay is None
    assert service._queue_size() == 1


@pytest.mark.asyncio
async def test_public_stats_fetches_only_aggregate_data_without_device_token(tmp_path):
    requests = []
    payload = {
        "total_devices": 128,
        "active_devices_7d": 31,
        "active_devices_30d": 77,
        "total_events": 45210,
        "generated_at": "2026-10-23T01:20:00Z",
        "future_field": "ignored by the API schema",
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    service = make_service(tmp_path, transport=httpx.MockTransport(handler))

    assert await service.fetch_public_stats() == payload
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/stats/public"
    assert "authorization" not in requests[0].headers


@pytest.mark.asyncio
async def test_public_stats_api_is_admin_only_and_ignores_unknown_fields(
    client,
    db_session,
    monkeypatch,
):
    regular_user = User(
        username="telemetry-user",
        full_name="Telemetry User",
        hashed_password="unused",
        is_active=True,
        is_superuser=False,
    )
    admin_user = User(
        username="telemetry-admin",
        full_name="Telemetry Admin",
        hashed_password="unused",
        is_active=True,
        is_superuser=True,
    )
    db_session.add_all([regular_user, admin_user])
    await db_session.commit()
    await db_session.refresh(regular_user)
    await db_session.refresh(admin_user)

    async def fetch_public_stats():
        return {
            "total_devices": 128,
            "active_devices_7d": 31,
            "active_devices_30d": 77,
            "total_events": 45210,
            "generated_at": "2026-10-23T01:20:00Z",
            "unknown_device_detail": "must not reach the client",
        }

    monkeypatch.setattr(telemetry, "fetch_public_stats", fetch_public_stats)

    regular_response = await client.get(
        "/api/v1/telemetry/stats/public",
        headers={"Authorization": f"Bearer {create_access_token(subject=regular_user.id)}"},
    )
    admin_response = await client.get(
        "/api/v1/telemetry/stats/public",
        headers={"Authorization": f"Bearer {create_access_token(subject=admin_user.id)}"},
    )

    assert regular_response.status_code == 400
    assert admin_response.status_code == 200
    assert admin_response.json() == {
        "total_devices": 128,
        "active_devices_7d": 31,
        "active_devices_30d": 77,
        "total_events": 45210,
        "generated_at": "2026-10-23T01:20:00Z",
    }
