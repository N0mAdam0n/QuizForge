import json

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.api.v1.endpoints.practice import _grade_answer
from app.models.practice_attempt import PracticeAttempt
from app.models.import_task import ImportTask, ImportTaskStatus
from app.models.question import Question, QuestionType
from app.models.subject import Subject
from app.models.subject_member import SubjectMember
from app.models.user import User
API = "/api/v1/practice"
_DOC = json.dumps({"type": "doc", "content": [{"type": "paragraph"}]})
_OPTION = {"type": "doc", "content": [{"type": "paragraph", "content": [
    {"type": "text", "text": "choice"}
]}]}


async def _seed_user(db_session, username: str) -> User:
    user = User(
        username=username,
        full_name=username,
        hashed_password="x",
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_question(
    db_session,
    *,
    subject: Subject,
    user: User,
    answer: dict | None,
    import_task: ImportTask,
    q_type: QuestionType = QuestionType.SINGLE_CHOICE,
    status: str = "published",
    visibility: str = "public",
) -> Question:
    options = [
        {"id": "a", "label": "A", "content": _OPTION},
        {"id": "b", "label": "B", "content": _OPTION},
    ] if q_type in {QuestionType.SINGLE_CHOICE, QuestionType.MULTIPLE_CHOICE} else None
    question = Question(
        content=_DOC,
        options=options,
        answer=json.dumps(answer) if answer is not None else None,
        q_type=q_type,
        status=status,
        subject_id=subject.id,
        import_task_id=import_task.id,
        created_by=user.id,
        visibility=visibility,
    )
    db_session.add(question)
    await db_session.commit()
    await db_session.refresh(question)
    return question


async def _seed_bank(db_session, user: User, *, scope: str = "shared") -> ImportTask:
    task = ImportTask(
        user_id=user.id,
        description="practice bank",
        source="test",
        file_path="virtual",
        original_filename="practice.json",
        file_type="json",
        status=ImportTaskStatus.COMPLETED,
        scope_type=scope,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(subject=user.id)}"}


@pytest.fixture
async def practice_context(db_session, grant_role):
    subject = Subject(name="练习学科", slug="practice")
    db_session.add(subject)
    await db_session.commit()
    await db_session.refresh(subject)
    user = await _seed_user(db_session, "practice_user")
    other = await _seed_user(db_session, "other_practice_user")
    await grant_role(user, subject)
    await grant_role(other, subject)
    return {"subject": subject, "user": user, "other": other}


async def test_practice_questions_hide_answers_and_exclude_unpublished(
    client, db_session, practice_context
):
    ctx = practice_context
    bank = await _seed_bank(db_session, ctx["user"])
    published = await _seed_question(
        db_session, subject=ctx["subject"], user=ctx["user"],
        answer={"kind": "single_choice", "correct": "a"}, import_task=bank,
    )
    second_published = await _seed_question(
        db_session, subject=ctx["subject"], user=ctx["user"],
        answer={"kind": "single_choice", "correct": "b"}, import_task=bank,
    )
    await _seed_question(
        db_session, subject=ctx["subject"], user=ctx["user"],
        answer={"kind": "single_choice", "correct": "b"}, import_task=bank, status="draft",
    )
    response = await client.get(
        f"{API}/questions",
        params={
            "subject_id": ctx["subject"].id,
            "scope": "shared",
            "import_task_id": bank.id,
            "mode": "sequential",
            "limit": 1,
        },
        headers=_auth(ctx["user"]),
    )

    assert response.status_code == 200, response.text
    questions = response.json()["questions"]
    assert [question["id"] for question in questions] == [published.id]
    assert response.json()["total_count"] == 2
    assert response.json()["has_more"] is True
    assert "answer" not in questions[0]
    assert "analysis" not in questions[0]

    next_page = await client.get(
        f"{API}/questions",
        params={
            "subject_id": ctx["subject"].id,
            "scope": "shared",
            "import_task_id": bank.id,
            "mode": "sequential",
            "limit": 1,
            "offset": response.json()["next_offset"],
        },
        headers=_auth(ctx["user"]),
    )
    assert [question["id"] for question in next_page.json()["questions"]] == [second_published.id]
    assert next_page.json()["total_count"] == 2
    assert next_page.json()["has_more"] is False


async def test_wrong_practice_is_scoped_to_the_answering_user(
    client, db_session, practice_context
):
    ctx = practice_context
    bank = await _seed_bank(db_session, ctx["user"])
    question = await _seed_question(
        db_session, subject=ctx["subject"], user=ctx["user"],
        answer={"kind": "single_choice", "correct": "a"}, import_task=bank,
    )
    submitted = await client.post(
        f"{API}/answers",
        headers=_auth(ctx["user"]),
        json={
            "question_id": question.id,
            "subject_id": ctx["subject"].id,
            "scope": "shared",
            "import_task_id": bank.id,
            "mode": "sequential",
            "answer": "b",
        },
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["is_correct"] is False
    assert submitted.json()["correct_answer"]["correct"] == "a"

    own_wrong = await client.get(
        f"{API}/questions",
        params={
            "subject_id": ctx["subject"].id,
            "scope": "shared",
            "import_task_id": bank.id,
            "mode": "wrong",
        },
        headers=_auth(ctx["user"]),
    )
    other_wrong = await client.get(
        f"{API}/questions",
        params={
            "subject_id": ctx["subject"].id,
            "scope": "shared",
            "import_task_id": bank.id,
            "mode": "wrong",
        },
        headers=_auth(ctx["other"]),
    )
    assert [item["id"] for item in own_wrong.json()["questions"]] == [question.id]
    assert other_wrong.json()["questions"] == []

    attempts = (
        await db_session.execute(select(PracticeAttempt))
    ).scalars().all()
    assert len(attempts) == 1


async def test_moving_bank_between_spaces_updates_visibility_and_review_state(
    client, db_session, practice_context
):
    ctx = practice_context
    bank = await _seed_bank(db_session, ctx["user"], scope="personal")
    question = await _seed_question(
        db_session,
        subject=ctx["subject"],
        user=ctx["user"],
        answer={"kind": "single_choice", "correct": "a"},
        import_task=bank,
        visibility="private",
    )

    shared = await client.put(
        f"{API}/question-banks/{bank.id}/scope",
        headers=_auth(ctx["user"]),
        json={"scope": "shared"},
    )
    assert shared.status_code == 200, shared.text
    await db_session.refresh(question)
    assert question.visibility == "public"
    assert question.status == "pending"
    assert question.review_count == 0

    personal = await client.put(
        f"{API}/question-banks/{bank.id}/scope",
        headers=_auth(ctx["user"]),
        json={"scope": "personal"},
    )
    assert personal.status_code == 200, personal.text
    await db_session.refresh(question)
    assert question.visibility == "private"
    assert question.status == "published"


async def test_personal_bank_is_hidden_from_other_users(client, db_session, practice_context):
    ctx = practice_context
    bank = await _seed_bank(db_session, ctx["user"], scope="personal")
    await _seed_question(
        db_session,
        subject=ctx["subject"],
        user=ctx["user"],
        answer={"kind": "single_choice", "correct": "a"},
        import_task=bank,
        visibility="private",
    )

    response = await client.get(
        f"{API}/question-banks/{bank.id}",
        params={"subject_id": ctx["subject"].id},
        headers=_auth(ctx["other"]),
    )
    assert response.status_code == 404


async def test_pending_personal_bank_is_not_practiceable_until_published(
    client, db_session, practice_context
):
    ctx = practice_context
    bank = await _seed_bank(db_session, ctx["user"], scope="personal")
    bank.publication_status = "pending"
    question = await _seed_question(
        db_session,
        subject=ctx["subject"],
        user=ctx["user"],
        answer={"kind": "single_choice", "correct": "a"},
        import_task=bank,
        status="pending",
        visibility="private",
    )
    await db_session.commit()

    manage = await client.get(
        f"{API}/manage-question-banks",
        params={"scope": "personal", "subject_id": ctx["subject"].id},
        headers=_auth(ctx["user"]),
    )
    assert manage.status_code == 200, manage.text
    assert manage.json()[0]["publication_status"] == "pending"

    before_publish = await client.get(
        f"{API}/question-banks",
        params={"scope": "personal", "subject_id": ctx["subject"].id},
        headers=_auth(ctx["user"]),
    )
    assert before_publish.json() == []

    published = await client.post(
        f"{API}/question-banks/{bank.id}/publish",
        headers=_auth(ctx["user"]),
    )
    assert published.status_code == 200, published.text
    assert published.json()["publication_status"] == "published"
    await db_session.refresh(question)
    assert question.status == "published"

    after_publish = await client.get(
        f"{API}/question-banks",
        params={"scope": "personal", "subject_id": ctx["subject"].id},
        headers=_auth(ctx["user"]),
    )
    assert [item["id"] for item in after_publish.json()] == [bank.id]


async def test_dont_know_records_wrong_answer_in_user_wrong_book(
    client, db_session, practice_context
):
    ctx = practice_context
    bank = await _seed_bank(db_session, ctx["user"], scope="personal")
    question = await _seed_question(
        db_session,
        subject=ctx["subject"],
        user=ctx["user"],
        answer={"kind": "single_choice", "correct": "a"},
        import_task=bank,
        visibility="private",
    )
    for _ in range(2):
        response = await client.post(
            f"{API}/answers",
            headers=_auth(ctx["user"]),
            json={
                "question_id": question.id,
                "subject_id": ctx["subject"].id,
                "scope": "personal",
                "import_task_id": bank.id,
                "mode": "sequential",
                "dont_know": True,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["is_correct"] is False
        assert response.json()["dont_know"] is True

    question.content = json.dumps(
        {"type": "doc", "content": [{"type": "paragraph", "content": [
            {"type": "text", "text": "updated question"}
        ]}]}
    )
    question.answer = json.dumps({"kind": "single_choice", "correct": "b"})
    await db_session.commit()

    wrong_book = await client.get(
        f"{API}/wrong-book",
        headers=_auth(ctx["user"]),
    )
    assert wrong_book.status_code == 200, wrong_book.text
    assert len(wrong_book.json()) == 1
    assert wrong_book.json()[0]["id"] == question.id
    assert wrong_book.json()[0]["wrong_count"] == 2
    assert wrong_book.json()[0]["answer"]["correct"] == "a"
    assert wrong_book.json()[0]["content"] == json.loads(_DOC)

    other_book = await client.get(f"{API}/wrong-book", headers=_auth(ctx["other"]))
    assert other_book.json() == []


async def test_fill_blank_uses_user_self_assessment(client, db_session, practice_context):
    ctx = practice_context
    bank = await _seed_bank(db_session, ctx["user"], scope="personal")
    question = await _seed_question(
        db_session,
        subject=ctx["subject"],
        user=ctx["user"],
        answer={"kind": "fill_in_the_blank", "blanks": [{"id": "b1", "accept": ["42"]}]},
        import_task=bank,
        q_type=QuestionType.FILL_IN_THE_BLANK,
        visibility="private",
    )
    response = await client.post(
        f"{API}/answers",
        headers=_auth(ctx["user"]),
        json={
            "question_id": question.id,
            "subject_id": ctx["subject"].id,
            "scope": "personal",
            "import_task_id": bank.id,
            "mode": "sequential",
            "answer": ["42"],
            "self_assessed": False,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_correct"] is False
    assert response.json()["correct_answer"]["blanks"][0]["accept"] == ["42"]


def test_fill_blank_uses_self_assessment_instead_of_automatic_grading():
    question = Question(
        q_type=QuestionType.FILL_IN_THE_BLANK,
        answer=json.dumps({"kind": "fill_in_the_blank", "blanks": [{"accept": ["42"]}]}),
    )
    assert _grade_answer(question, ["42"]) == (None, None, True)


@pytest.mark.parametrize(
    ("q_type", "answer", "submitted", "expected", "score"),
    [
        (
            QuestionType.SINGLE_CHOICE,
            {"kind": "single_choice", "correct": "a"},
            "a", True, 1.0,
        ),
        (
            QuestionType.MULTIPLE_CHOICE,
            {"kind": "multiple_choice", "correct": ["a", "b"], "grading": "partial"},
            ["a"], False, 0.5,
        ),
        (
            QuestionType.TRUE_FALSE,
            {"kind": "true_false", "correct": False},
            False, True, 1.0,
        ),
    ],
)
def test_auto_grading_supported_question_types(
    q_type, answer, submitted, expected, score
):
    question = Question(q_type=q_type, answer=json.dumps(answer))

    is_correct, actual_score, requires_self_assessment = _grade_answer(question, submitted)

    assert is_correct is expected
    assert actual_score == score
    assert requires_self_assessment is False


def test_multiple_choice_rejects_non_string_option_ids():
    question = Question(
        q_type=QuestionType.MULTIPLE_CHOICE,
        answer=json.dumps({"kind": "multiple_choice", "correct": ["a"]}),
    )
    assert _grade_answer(question, [{"unexpected": "object"}]) == (False, 0.0, False)
