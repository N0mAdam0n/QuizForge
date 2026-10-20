import json

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.api.v1.endpoints.practice import _grade_answer
from app.models.practice_attempt import PracticeAttempt
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
    q_type: QuestionType = QuestionType.SINGLE_CHOICE,
    status: str = "published",
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
        created_by=user.id,
        visibility="public",
    )
    db_session.add(question)
    await db_session.commit()
    await db_session.refresh(question)
    return question


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
    published = await _seed_question(
        db_session, subject=ctx["subject"], user=ctx["user"],
        answer={"kind": "single_choice", "correct": "a"},
    )
    second_published = await _seed_question(
        db_session, subject=ctx["subject"], user=ctx["user"],
        answer={"kind": "single_choice", "correct": "b"},
    )
    await _seed_question(
        db_session, subject=ctx["subject"], user=ctx["user"],
        answer={"kind": "single_choice", "correct": "b"}, status="draft",
    )
    response = await client.get(
        f"{API}/questions",
        params={"subject_id": ctx["subject"].id, "mode": "sequential", "limit": 1},
        headers=_auth(ctx["user"]),
    )

    assert response.status_code == 200, response.text
    questions = response.json()["questions"]
    assert [question["id"] for question in questions] == [published.id]
    assert response.json()["has_more"] is True
    assert "answer" not in questions[0]
    assert "analysis" not in questions[0]

    next_page = await client.get(
        f"{API}/questions",
        params={
            "subject_id": ctx["subject"].id,
            "mode": "sequential",
            "limit": 1,
            "offset": response.json()["next_offset"],
        },
        headers=_auth(ctx["user"]),
    )
    assert [question["id"] for question in next_page.json()["questions"]] == [second_published.id]
    assert next_page.json()["has_more"] is False


async def test_wrong_practice_is_scoped_to_the_answering_user(
    client, db_session, practice_context
):
    ctx = practice_context
    question = await _seed_question(
        db_session, subject=ctx["subject"], user=ctx["user"],
        answer={"kind": "single_choice", "correct": "a"},
    )
    submitted = await client.post(
        f"{API}/answers",
        headers=_auth(ctx["user"]),
        json={
            "question_id": question.id,
            "subject_id": ctx["subject"].id,
            "mode": "sequential",
            "answer": "b",
        },
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["is_correct"] is False
    assert submitted.json()["correct_answer"]["correct"] == "a"

    own_wrong = await client.get(
        f"{API}/questions",
        params={"subject_id": ctx["subject"].id, "mode": "wrong"},
        headers=_auth(ctx["user"]),
    )
    other_wrong = await client.get(
        f"{API}/questions",
        params={"subject_id": ctx["subject"].id, "mode": "wrong"},
        headers=_auth(ctx["other"]),
    )
    assert [item["id"] for item in own_wrong.json()["questions"]] == [question.id]
    assert other_wrong.json()["questions"] == []

    attempts = (
        await db_session.execute(select(PracticeAttempt))
    ).scalars().all()
    assert len(attempts) == 1


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
        (
            QuestionType.FILL_IN_THE_BLANK,
            {"kind": "fill_in_the_blank", "blanks": [{"accept": [" 42 "], "match": "ignore_space"}]},
            ["42"], True, 1.0,
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
