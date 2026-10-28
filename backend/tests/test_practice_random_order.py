from tests.test_practice_api import API, _auth, _seed_bank, _seed_question, practice_context  # noqa: F401


async def _seed(db_session, ctx, n=30):
    bank = await _seed_bank(db_session, ctx["user"])
    ids = []
    for _ in range(n):
        q = await _seed_question(
            db_session, subject=ctx["subject"], user=ctx["user"],
            answer={"kind": "single_choice", "correct": "a"}, import_task=bank,
        )
        ids.append(q.id)
    return bank, ids


async def test_random_mode_all_returns_every_question_in_shuffled_order(client, db_session, practice_context):
    ctx = practice_context
    bank, ids = await _seed(db_session, ctx)
    params = {"subject_id": ctx["subject"].id, "scope": "shared", "import_task_id": bank.id,
              "mode": "random", "random_count": "all"}
    orders = []
    for _ in range(5):
        r = await client.get(f"{API}/questions", params=params, headers=_auth(ctx["user"]))
        assert r.status_code == 200, r.text
        body = r.json()
        got = [q["id"] for q in body["questions"]]
        assert sorted(got) == sorted(ids) and body["total_count"] == len(ids) and body["has_more"] is False
        orders.append(tuple(got))
    # 30! orderings: five identical sorted results would mean no shuffling at all
    assert any(o != tuple(sorted(ids)) for o in orders)
    assert len(set(orders)) > 1


async def test_random_mode_count_is_a_random_subset(client, db_session, practice_context):
    ctx = practice_context
    bank, ids = await _seed(db_session, ctx)
    params = {"subject_id": ctx["subject"].id, "scope": "shared", "import_task_id": bank.id,
              "mode": "random", "random_count": "20"}
    r = await client.get(f"{API}/questions", params=params, headers=_auth(ctx["user"]))
    got = [q["id"] for q in r.json()["questions"]]
    assert len(got) == 20 and len(set(got)) == 20 and set(got) <= set(ids)


async def test_questions_per_round_up_to_100_is_accepted(client, db_session, practice_context):
    ctx = practice_context
    bank, ids = await _seed(db_session, ctx, n=3)
    params = {"subject_id": ctx["subject"].id, "scope": "shared", "import_task_id": bank.id, "limit": 100}
    r = await client.get(f"{API}/questions", params=params, headers=_auth(ctx["user"]))
    assert r.status_code == 200 and len(r.json()["questions"]) == 3
    r = await client.get(f"{API}/questions", params={**params, "limit": 101}, headers=_auth(ctx["user"]))
    assert r.status_code == 422
