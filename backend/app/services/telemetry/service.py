from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import platform
import random
import re
import secrets
import socket
import sqlite3
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app._version import __version__
from app.core.config import Settings, settings

logger = logging.getLogger(__name__)

_MAX_QUEUE_SIZE = 10_000
_BATCH_SIZE = 50
_MAX_BACKOFF_SECONDS = 30 * 60
_SAFE_SHORT = re.compile(r"[^A-Za-z0-9._\- ]")
_QUESTION_TYPES = {
    "single_choice",
    "multiple_choice",
    "true_false",
    "fill_in_the_blank",
    "free_response",
}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _short(value: str | None) -> str | None:
    if value is None:
        return None
    sanitized = _SAFE_SHORT.sub("", value)[:32]
    return sanitized or None


class TelemetryService:
    """Opt-in, local-queue backed telemetry sender.

    Events are intentionally built from allowlisted scalar fields only; this
    service never accepts question text, filenames, usernames, or source data.
    """

    def __init__(
        self,
        configured: Settings = settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = configured
        self.transport = transport
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._attempts_since_success = 0

    @property
    def enabled(self) -> bool:
        return self.settings.TELEMETRY_ENABLED

    @property
    def consent_path(self) -> Path:
        return self.settings.DATA_DIR / "telemetry.json"

    @property
    def queue_path(self) -> Path:
        return self.settings.DATA_DIR / "telemetry_queue.db"

    def consent_status(self) -> bool:
        if not self.enabled:
            return False
        data = self._read_consent()
        salt = data.get("salt") if data else None
        return bool(
            data
            and data.get("consent") is True
            and isinstance(salt, str)
            and len(salt) == 64
        )

    def _read_consent(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.consent_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read telemetry consent state")
            return None
        return data if isinstance(data, dict) else None

    def _write_consent(self, data: dict[str, Any]) -> None:
        self.settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        temp_path = self.consent_path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(data, ensure_ascii=True, separators=(",", ":")),
            encoding="utf-8",
        )
        if os.name != "nt":
            os.chmod(temp_path, 0o600)
        os.replace(temp_path, self.consent_path)

    def set_consent(self, consent: bool) -> bool:
        """Persist a decision; a positive decision is the only path creating state."""
        if not self.enabled:
            return False
        if consent:
            state = self._read_consent() or {}
            salt = state.get("salt")
            if (
                state.get("consent") is not True
                or not isinstance(salt, str)
                or len(salt) != 64
            ):
                state = {
                    "consent": True,
                    "salt": secrets.token_bytes(32).hex(),
                    "device_id": None,
                    "token": None,
                }
                self._write_consent(state)
                self.emit_app_meta()
            else:
                state["consent"] = True
                self._write_consent(state)
            self._initialize_queue()
            self._wake.set()
            return True

        self._clear_queue()
        try:
            self.consent_path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove telemetry credentials after consent withdrawal")
            raise
        self._wake.set()
        return False

    def _initialize_queue(self) -> None:
        if not self.enabled or not self.consent_status():
            return
        self.settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.queue_path, timeout=5) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS queue "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, json TEXT NOT NULL, "
                "created_at TEXT NOT NULL, tries INTEGER NOT NULL DEFAULT 0)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS attempts "
                "(item_hash TEXT PRIMARY KEY, attempt_no INTEGER NOT NULL)"
            )
        if os.name != "nt":
            os.chmod(self.queue_path, 0o600)

    def _clear_queue(self) -> None:
        if not self.queue_path.exists():
            return
        with sqlite3.connect(self.queue_path, timeout=5) as db:
            db.execute("DELETE FROM queue")
            db.execute("DELETE FROM attempts")

    def _hash(self, value: Any) -> str | None:
        state = self._read_consent()
        salt_hex = state.get("salt") if state else None
        if (
            not state
            or state.get("consent") is not True
            or not isinstance(salt_hex, str)
            or len(salt_hex) != 64
        ):
            return None
        try:
            salt = bytes.fromhex(salt_hex)
        except ValueError:
            return None
        if len(salt) != 32:
            return None
        return hashlib.sha256(salt + str(value).encode("utf-8")).hexdigest()

    def emit(self, event: dict[str, Any]) -> None:
        """Queue one already-sanitized event without making a network request."""
        if not self.enabled or not self.consent_status():
            return
        try:
            self._initialize_queue()
            with sqlite3.connect(self.queue_path, timeout=5) as db:
                db.execute(
                    "INSERT INTO queue(json, created_at, tries) VALUES (?, ?, 0)",
                    (json.dumps(event, ensure_ascii=True, separators=(",", ":")), _now()),
                )
                db.execute(
                    "DELETE FROM queue WHERE id NOT IN "
                    "(SELECT id FROM queue ORDER BY id DESC LIMIT ?)",
                    (_MAX_QUEUE_SIZE,),
                )
            self._wake.set()
        except Exception:
            logger.warning("Could not enqueue telemetry event", exc_info=True)

    def emit_app_meta(self) -> None:
        if not self.enabled or not self.consent_status():
            return
        try:
            system_name = platform.system().lower()
            os_name = {
                "windows": "windows",
                "darwin": "macos",
                "linux": "linux",
            }.get(system_name, "other")
            self.emit(
                {
                    "event_type": "app_meta",
                    "schema_version": 1,
                    "client_ts": _now(),
                    "app_version": _short(__version__) or "0.0.0",
                    "os": os_name,
                    "os_version": _short(platform.release()),
                    "locale": _short(
                        os.getenv("LANG")
                        or os.getenv("LC_ALL")
                        or os.getenv("LANGUAGE")
                    ),
                }
            )
        except Exception:
            logger.warning("Could not create app metadata telemetry", exc_info=True)

    def emit_import_parse(
        self,
        *,
        task_id: str | int,
        diagnostics: Any,
        doc_format: str,
    ) -> None:
        if not self.enabled or not self.consent_status() or diagnostics is None:
            return
        doc_hash = self._hash(task_id)
        if doc_hash is None:
            return
        try:
            chosen = diagnostics["chosen_strategy"]
            details = diagnostics["ai_details"] if chosen == "ai" else diagnostics["local_details"]
            if details is None:
                return
            ai_details = diagnostics.get("ai_details")
            questions = diagnostics.get("questions", [])
            expected = min(max(int(details.get("expected_count") or 0), 0), 10_000)
            extracted = min(max(int(details.get("extracted_count") or 0), 0), 10_000)
            raw_coverage = min(max(float(details.get("raw_coverage") or 0), -10), 10)
            duration = min(max(int(diagnostics.get("latency_ms") or 0), 0), 600_000)
            fmt = doc_format if doc_format in {"docx", "pdf", "md", "txt", "image"} else "other"
            for index, question in enumerate(questions[:10_001]):
                q_type = question.get("q_type")
                if hasattr(q_type, "value"):
                    q_type = q_type.value
                q_type = q_type if q_type in _QUESTION_TYPES else "unknown"
                event: dict[str, Any] = {
                    "event_type": "import_parse",
                    "schema_version": 1,
                    "client_ts": _now(),
                    "doc_id_hash": doc_hash,
                    "question_index": index,
                    "question_type": q_type,
                    "rule_score_q": min(max(float(details["quality"]), 0), 1),
                    "completeness_c": min(max(float(details["coverage"]), 0), 1),
                    "combined_s": min(max(float(details["combined"]), 0), 1),
                    "question_rule_score": min(
                        max(float(details["per_question"][index]), 0), 1
                    ),
                    "raw_q": min(max(float(details["quality"]), -10), 10),
                    "raw_c": raw_coverage,
                    "threshold": min(max(float(diagnostics["threshold"]), 0), 1),
                    "chosen_strategy": chosen,
                    "ai_called": bool(diagnostics["ai_called"]),
                    "latency_ms": duration,
                    "doc_format": fmt,
                    "expected_count": expected,
                    "extracted_count": extracted,
                }
                if ai_details is not None:
                    event["ai_score"] = min(max(float(ai_details["combined"]), 0), 1)
                self.emit(event)
        except (KeyError, TypeError, ValueError, IndexError):
            logger.warning("Could not create import telemetry events", exc_info=True)

    def emit_practice_answer(
        self,
        *,
        question_id: int,
        question_type: str,
        correct: bool | None,
        time_ms: int | None,
        session_id: str | None,
    ) -> None:
        if correct is None or not self.consent_status():
            return
        item_hash = self._hash(question_id)
        if item_hash is None:
            return
        try:
            self._initialize_queue()
            with sqlite3.connect(self.queue_path, timeout=5) as db:
                row = db.execute(
                    "SELECT attempt_no FROM attempts WHERE item_hash = ?", (item_hash,)
                ).fetchone()
                attempt_no = int(row[0]) + 1 if row else 1
                db.execute(
                    "INSERT INTO attempts(item_hash, attempt_no) VALUES (?, ?) "
                    "ON CONFLICT(item_hash) DO UPDATE SET attempt_no = excluded.attempt_no",
                    (item_hash, attempt_no),
                )
            q_type = question_type if question_type in _QUESTION_TYPES else "unknown"
            event: dict[str, Any] = {
                "event_type": "practice_answer",
                "schema_version": 1,
                "client_ts": _now(),
                "item_hash": item_hash,
                "question_type": q_type,
                "correct": bool(correct),
                "time_ms": min(max(int(time_ms or 0), 0), 3_600_000),
                "attempt_no": min(attempt_no, 1000),
            }
            if session_id:
                session_hash = self._hash(session_id)
                if session_hash:
                    event["session_hash"] = session_hash
            self.emit(event)
        except Exception:
            logger.warning("Could not create practice telemetry event", exc_info=True)

    def emit_review_edit(
        self,
        *,
        question_id: int,
        import_task_id: int | None,
        fields_changed: list[str],
        accepted_unchanged: bool,
        edit_category: str,
        question_index: int | None = None,
        edit_distance: int | None = None,
    ) -> None:
        try:
            question_hash = self._hash(question_id)
            if question_hash is None:
                return
            allowed_fields = {
                "content", "options", "answer", "analysis", "q_type", "difficulty", "tags", "other"
            }
            allowed_categories = {
                "typo", "boundary_split", "boundary_merge", "option_fix", "answer_fix",
                "type_fix", "format", "delete", "other",
            }
            event: dict[str, Any] = {
                "event_type": "review_edit",
                "schema_version": 1,
                "client_ts": _now(),
                "question_ref_hash": question_hash,
                "fields_changed": [field for field in fields_changed if field in allowed_fields][:8],
                "edit_category": edit_category if edit_category in allowed_categories else "other",
                "accepted_unchanged": accepted_unchanged,
            }
            task_hash = self._hash(import_task_id) if import_task_id is not None else None
            if task_hash:
                event["doc_id_hash"] = task_hash
            if question_index is not None and 0 <= question_index <= 10_000:
                event["question_index"] = question_index
            if edit_distance is not None:
                event["edit_distance"] = min(max(int(edit_distance), 0), 100_000)
            self.emit(event)
        except Exception:
            logger.warning("Could not create review telemetry event", exc_info=True)

    def _load_batch(self) -> list[tuple[int, dict[str, Any]]]:
        if not self.queue_path.exists():
            return []
        with sqlite3.connect(self.queue_path, timeout=5) as db:
            rows = db.execute(
                "SELECT id, json FROM queue ORDER BY id LIMIT ?", (_BATCH_SIZE,)
            ).fetchall()
        return [(int(row[0]), json.loads(row[1])) for row in rows]

    def _queue_size(self) -> int:
        if not self.queue_path.exists():
            return 0
        with sqlite3.connect(self.queue_path, timeout=5) as db:
            row = db.execute("SELECT COUNT(*) FROM queue").fetchone()
        return int(row[0])

    def _delete_rows(self, row_ids: list[int]) -> None:
        if not row_ids or not self.queue_path.exists():
            return
        marks = ",".join("?" for _ in row_ids)
        with sqlite3.connect(self.queue_path, timeout=5) as db:
            db.execute(f"DELETE FROM queue WHERE id IN ({marks})", row_ids)

    def _increment_tries(self, row_ids: list[int]) -> None:
        if not row_ids or not self.queue_path.exists():
            return
        marks = ",".join("?" for _ in row_ids)
        with sqlite3.connect(self.queue_path, timeout=5) as db:
            db.execute(f"UPDATE queue SET tries = tries + 1 WHERE id IN ({marks})", row_ids)

    def _save_credentials(self, device_id: str | None, token: str | None) -> None:
        state = self._read_consent() or {}
        if state.get("consent") is not True:
            return
        state.update({"device_id": device_id, "token": token})
        self._write_consent(state)

    async def _ssl_context(self, endpoint: str) -> ssl.SSLContext | bool:
        parsed = urlparse(endpoint)
        if parsed.scheme == "http":
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("Telemetry HTTP is permitted only for loopback endpoints")
            return True
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Telemetry endpoint must use HTTPS")

        pin = self.settings.TELEMETRY_CERT_SHA256.replace(":", "").upper()

        def read_pinned_certificate() -> bytes:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            with socket.create_connection((parsed.hostname, parsed.port or 443), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=parsed.hostname) as tls:
                    certificate = tls.getpeercert(binary_form=True)
            got = hashlib.sha256(certificate).hexdigest().upper()
            if got != pin:
                raise ssl.SSLError("telemetry certificate pin mismatch")
            return certificate

        certificate = await asyncio.to_thread(read_pinned_certificate)
        pem = ssl.DER_cert_to_PEM_cert(certificate)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=pem)
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        return context

    async def _register(self, client: httpx.AsyncClient) -> bool:
        response = await client.post(
            "/v1/devices/register",
            json={"consent": True, "app_version": _short(__version__)},
        )
        if response.status_code != 201:
            logger.warning("Telemetry device registration failed with HTTP %s", response.status_code)
            return False
        data = response.json()
        device_id, token = data.get("device_id"), data.get("token")
        if not isinstance(device_id, str) or not isinstance(token, str):
            logger.warning("Telemetry registration returned an invalid response")
            return False
        self._save_credentials(device_id, token)
        return True

    async def _ensure_registered(self, client: httpx.AsyncClient) -> bool:
        state = self._read_consent() or {}
        if state.get("consent") is not True:
            return False
        if state.get("device_id") and state.get("token"):
            return True
        return await self._register(client)

    async def _send_rows(
        self,
        client: httpx.AsyncClient,
        rows: list[tuple[int, dict[str, Any]]],
        *,
        allow_reregister: bool = True,
    ) -> tuple[str, float | None]:
        if not rows or not self.consent_status():
            return "done", None
        if not await self._ensure_registered(client):
            return "retry", None
        state = self._read_consent() or {}
        response: httpx.Response
        try:
            response = await client.post(
                "/v1/events",
                headers={"Authorization": f"Bearer {state['token']}"},
                json={"events": [event for _, event in rows]},
            )
        except (httpx.TimeoutException, httpx.NetworkError, ssl.SSLError, OSError):
            logger.warning("Telemetry upload could not reach the configured endpoint")
            return "retry", None

        if response.status_code == 202:
            self._delete_rows([row_id for row_id, _ in rows])
            self._attempts_since_success = 0
            return "done", None
        if response.status_code == 401:
            self._save_credentials(None, None)
            if allow_reregister and await self._register(client):
                return await self._send_rows(client, rows, allow_reregister=False)
            logger.warning("Telemetry authentication failed; upload paused until next retry")
            return "retry", None
        if response.status_code in {400, 422}:
            detail = response.text[:500]
            logger.warning("Telemetry batch rejected with HTTP %s: %s", response.status_code, detail)
            self._delete_rows([row_id for row_id, _ in rows])
            return "done", None
        if response.status_code == 413:
            if len(rows) == 1:
                logger.warning("Dropping a telemetry event rejected as oversized")
                self._delete_rows([rows[0][0]])
                return "done", None
            midpoint = len(rows) // 2
            first = await self._send_rows(
                client, rows[:midpoint], allow_reregister=allow_reregister
            )
            if first[0] == "retry":
                return first
            return await self._send_rows(
                client, rows[midpoint:], allow_reregister=allow_reregister
            )
        if response.status_code == 429:
            try:
                retry_after = float(response.headers.get("Retry-After", "30"))
            except ValueError:
                retry_after = 30
            return "retry", min(max(retry_after, 1), _MAX_BACKOFF_SECONDS)
        if response.status_code >= 500:
            logger.warning("Telemetry endpoint returned HTTP %s", response.status_code)
            return "retry", None
        logger.warning("Telemetry upload returned unexpected HTTP %s", response.status_code)
        return "retry", None

    async def fetch_public_stats(self) -> dict[str, Any]:
        async with await self._make_client(timeout=5) as client:
            response = await client.get("/v1/stats/public")
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Telemetry public stats response must be an object")
        return data

    async def _make_client(self, *, timeout: float = 10) -> httpx.AsyncClient:
        endpoint = self.settings.TELEMETRY_ENDPOINT.rstrip("/")
        verify = await self._ssl_context(endpoint)
        return httpx.AsyncClient(
            base_url=endpoint,
            verify=verify,
            timeout=timeout,
            transport=self.transport,
            trust_env=False,
        )

    async def run(self) -> None:
        """Drain batches in the background; no DB file is touched before consent."""
        self._stop = asyncio.Event()
        interval = 180.0
        while not self._stop.is_set():
            if not self.enabled or not self.consent_status():
                await self._wait(5)
                continue
            try:
                self._initialize_queue()
                queued = self._queue_size()
                if queued == 0:
                    await self._wait(180)
                    continue
                if queued < _BATCH_SIZE:
                    await self._wait(180)
                    continue
                batch = self._load_batch()
                self._increment_tries([row_id for row_id, _ in batch])
                async with await self._make_client() as client:
                    result, delay = await self._send_rows(client, batch)
                if result == "retry":
                    self._attempts_since_success += 1
                    base = delay or min(30 * (2 ** min(self._attempts_since_success - 1, 10)), _MAX_BACKOFF_SECONDS)
                    interval = min(base * random.uniform(0.8, 1.2), _MAX_BACKOFF_SECONDS)
                else:
                    interval = 30.0 if self._queue_size() >= _BATCH_SIZE else 180.0
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Telemetry background upload failed", exc_info=True)
                self._attempts_since_success += 1
                base = min(30 * (2 ** min(self._attempts_since_success - 1, 10)), _MAX_BACKOFF_SECONDS)
                interval = min(base * random.uniform(0.8, 1.2), _MAX_BACKOFF_SECONDS)
            await self._wait(interval)

    async def _wait(self, seconds: float) -> None:
        self._wake.clear()
        stop_task = asyncio.create_task(self._stop.wait())
        wake_task = asyncio.create_task(self._wake.wait())
        try:
            await asyncio.wait(
                {stop_task, wake_task},
                timeout=seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in (stop_task, wake_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stop_task, wake_task, return_exceptions=True)

    def stop(self) -> None:
        self._stop.set()


telemetry = TelemetryService()
