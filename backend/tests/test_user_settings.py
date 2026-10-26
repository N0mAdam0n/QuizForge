import csv
import io
import json

import pytest
from sqlalchemy import func, select

from app.models.practice_attempt import PracticeAttempt
from app.models.subject import Subject
from tests.test_practice_api import _auth, _seed_bank, _seed_question, _seed_user

USERS = "/api/v1/users"
PRACTICE = "/api/v1/practice"


async def test_preferences_defaults_update_and_validation(client, db_session):
    user = await _seed_user(db_session, "pref-user")
    r = await client.get(f"{USERS}/me/preferences", headers=_auth(user))
    assert r.status_code == 200
    assert r.json()["questions_per_round"] == 20
    assert r.json()["show_explanation_immediately"] is True

    r = await client.put(f"{USERS}/me/preferences", headers=_auth(user),
                         json={"questions_per_round": 40, "theme": "dark", "shuffle_options": True})
    assert r.status_code == 200
    body = r.json()
    assert body["questions_per_round"] == 40 and body["theme"] == "dark" and body["shuffle_options"] is True
    assert body["default_mode"] == "sequential"

    # partial update keeps previous values
    r = await client.put(f"{USERS}/me/preferences", headers=_auth(user), json={"font_size": "large"})
    assert r.json()["questions_per_round"] == 40 and r.json()["font_size"] == "large"

    for bad in ({"questions_per_round": 7}, {"theme": "neon"}, {"unknown": 1}):
        assert (await client.put(f"{USERS}/me/preferences", headers=_auth(user), json=bad)).status_code == 422

    other = await _seed_user(db_session, "pref-other")
    assert (await client.get(f"{USERS}/me/preferences", headers=_auth(other))).json()["theme"] == "auto"


async def test_nickname_update(client, db_session):
    user = await _seed_user(db_session, "nick-user")
    r = await client.put(f"{USERS}/me/nickname", headers=_auth(user), json={"full_name": "  小明 "})
    assert r.status_code == 200 and r.json()["full_name"] == "小明"
    assert (await client.put(f"{USERS}/me/nickname", headers=_auth(user), json={"full_name": ""})).status_code == 422


@pytest.fixture
async def history(db_session):
    subject = Subject(name="历史学科", slug="history-subj")
    db_session.add(subject)
    await db_session.commit()
    await db_session.refresh(subject)
    alice = await _seed_user(db_session, "hist-alice")
    bob = await _seed_user(db_session, "hist-bob")
    bank = await _seed_bank(db_session, alice)
    q = await _seed_question(db_session, subject=subject, user=alice, answer={"option_ids": ["a"]}, import_task=bank)
    for user, correct in ((alice, True), (alice, False), (bob, True)):
        db_session.add(PracticeAttempt(user_id=user.id, question_id=q.id, subject_id=subject.id,
                                       mode="sequential", submitted_answer="a", is_correct=correct, score=None))
    await db_session.commit()
    return alice, bob


async def test_export_history_only_own_rows(client, history):
    alice, _bob = history
    r = await client.get(f"{PRACTICE}/history/export", params={"format": "json"}, headers=_auth(alice))
    assert r.status_code == 200
    rows = json.loads(r.text)
    assert len(rows) == 2 and {row["is_correct"] for row in rows} == {True, False}

    r = await client.get(f"{PRACTICE}/history/export", params={"format": "csv"}, headers=_auth(alice))
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    parsed = list(csv.DictReader(io.StringIO(r.text.lstrip("\ufeff"))))
    assert len(parsed) == 2 and "question_id" in parsed[0]

    assert (await client.get(f"{PRACTICE}/history/export", params={"format": "xml"},
                             headers=_auth(alice))).status_code == 422


async def test_clear_history_requires_confirm_and_only_own(client, db_session, history):
    alice, bob = history
    assert (await client.delete(f"{PRACTICE}/history", headers=_auth(alice))).status_code == 422
    assert (await client.delete(f"{PRACTICE}/history", params={"confirm": "yes"},
                                headers=_auth(alice))).status_code == 400
    r = await client.delete(f"{PRACTICE}/history", params={"confirm": "CLEAR"}, headers=_auth(alice))
    assert r.status_code == 200 and r.json()["deleted"] == 2
    left = (await db_session.execute(select(func.count()).select_from(PracticeAttempt))).scalar_one()
    assert left == 1
    mine = (await db_session.execute(select(func.count()).select_from(PracticeAttempt)
                                     .where(PracticeAttempt.user_id == bob.id))).scalar_one()
    assert mine == 1


async def test_public_usage_stats_visible_to_normal_users(client, db_session, monkeypatch):
    from app.services.telemetry import telemetry

    async def fake():
        return {"total_devices": 3, "active_devices_7d": 1, "active_devices_30d": 2,
                "total_events": 9, "total_users": 2, "generated_at": "2026-10-26T08:00:00Z"}

    monkeypatch.setattr(telemetry, "fetch_public_stats", fake)
    user = await _seed_user(db_session, "stats-user")
    r = await client.get("/api/v1/telemetry/stats/public", headers=_auth(user))
    assert r.status_code == 200 and r.json()["total_users"] == 2
