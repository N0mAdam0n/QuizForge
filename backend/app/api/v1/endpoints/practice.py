import re
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from app.api import deps
from app.crud.crud_question import visible_questions_filter
from app.models.practice_attempt import PracticeAttempt
from app.models.question import Question, QuestionStatus, QuestionType
from app.models.user import User
from app.schemas.practice import (
    PracticeAnswerResult,
    PracticeAnswerSubmit,
    PracticeMode,
    PracticeQuestion,
    PracticeQuestionSet,
)
from app.services.question_content import parse_json_field

router = APIRouter()
_VALID_MODES = {"sequential", "random", "type", "wrong"}


def _safe_question(question: Question) -> PracticeQuestion | None:
    answer = parse_json_field(question.answer)
    if not isinstance(answer, dict) or answer.get("kind") == "legacy_unresolved":
        return None
    content = parse_json_field(question.content)
    if not isinstance(content, dict):
        raise ValueError(f"Question {question.id} has invalid rich-text content")
    return PracticeQuestion(
        id=question.id,
        content=content,
        q_type=question.q_type,
        options=question.options or [],
        difficulty=question.difficulty or 1,
    )


def _rich_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    parts: list[str] = []
    if value.get("type") == "text":
        parts.append(str(value.get("text") or ""))
    attrs = value.get("attrs")
    if isinstance(attrs, dict):
        parts.append(str(attrs.get("latex") or attrs.get("text") or ""))
    for child in value.get("content") or []:
        parts.append(_rich_text(child))
    return "".join(parts)


def _normalize_blank(value: str, match: str | None) -> str | Decimal | None:
    normalized = value.strip()
    if match == "ignore_space":
        normalized = re.sub(r"\s+", "", normalized)
    elif match == "ignore_case":
        normalized = normalized.casefold()
    elif match == "numeric":
        try:
            return Decimal(normalized.replace(",", ""))
        except InvalidOperation:
            return None
    return normalized


def _grade_answer(question: Question, submitted: Any) -> tuple[bool | None, float | None, bool]:
    answer = parse_json_field(question.answer)
    if not isinstance(answer, dict) or answer.get("kind") == "legacy_unresolved":
        return None, None, True

    answer_kind = answer.get("kind")
    if answer_kind == "single_choice":
        correct = str(answer.get("correct") or "")
        is_correct = isinstance(submitted, str) and submitted == correct
        return is_correct, float(is_correct), False
    if answer_kind == "multiple_choice":
        correct_values = answer.get("correct") or []
        if not isinstance(correct_values, list) or not all(
            isinstance(value, str) for value in correct_values
        ):
            return None, None, True
        if not isinstance(submitted, list) or not all(
            isinstance(value, str) for value in submitted
        ):
            return False, 0.0, False
        selected = set(submitted)
        correct = set(correct_values)
        if answer.get("grading") == "partial":
            score = len(correct & selected) / len(correct) if correct else 0.0
            if selected - correct:
                score = 0.0
        else:
            score = float(selected == correct)
        return selected == correct, score, False
    if answer_kind == "true_false":
        is_correct = isinstance(submitted, bool) and submitted is answer.get("correct")
        return is_correct, float(is_correct), False
    if answer_kind == "fill_in_the_blank":
        blanks = answer.get("blanks") or []
        if not isinstance(submitted, list) or len(submitted) != len(blanks):
            return False, 0.0, False
        matched = 0
        for value, blank in zip(submitted, blanks):
            if not isinstance(value, str) or not isinstance(blank, dict):
                continue
            match = blank.get("match") or "exact"
            expected = [
                _normalize_blank(_rich_text(accepted), match)
                for accepted in blank.get("accept") or []
            ]
            actual = _normalize_blank(value, match)
            if actual is not None and actual in expected:
                matched += 1
        score = matched / len(blanks) if blanks else 0.0
        return score == 1.0, score, False
    if answer_kind == "free_response":
        return None, None, True
    return None, None, True


@router.get("/questions", response_model=PracticeQuestionSet)
async def read_practice_questions(
    db: deps.SessionDep,
    subject_id: int,
    mode: PracticeMode = "sequential",
    q_type: QuestionType | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(deps.get_current_active_user),
) -> PracticeQuestionSet:
    if mode not in _VALID_MODES:
        raise HTTPException(status_code=422, detail="Unsupported practice mode")
    if mode == "type" and q_type is None:
        raise HTTPException(status_code=422, detail="q_type is required for type practice")
    if mode != "type" and q_type is not None:
        raise HTTPException(status_code=422, detail="q_type is only valid for type practice")

    stmt = select(Question).where(
        Question.subject_id == subject_id,
        Question.status == QuestionStatus.PUBLISHED.value,
        Question.deleted_at.is_(None),
        Question.parent_id.is_(None),
        Question.answer.is_not(None),
        visible_questions_filter(current_user),
    )
    if mode == "type" and q_type is not None:
        stmt = stmt.where(Question.q_type == q_type)
    if mode == "wrong":
        wrong_questions = (
            select(PracticeAttempt.question_id)
            .where(
                PracticeAttempt.user_id == current_user.id,
                PracticeAttempt.subject_id == subject_id,
                PracticeAttempt.is_correct.is_(False),
            )
            .distinct()
        )
        stmt = stmt.where(Question.id.in_(wrong_questions))

    if mode == "random":
        stmt = stmt.order_by(
            func.rand() if db.bind and db.bind.dialect.name == "mysql" else func.random()
        )
    else:
        stmt = stmt.order_by(Question.id)
    questions: list[PracticeQuestion] = []
    has_more = False
    next_offset = offset
    if mode == "random":
        rows = (await db.execute(stmt.limit(limit + 1))).scalars().all()
        for row in rows:
            safe = _safe_question(row)
            if safe is not None:
                questions.append(safe)
            if len(questions) > limit:
                break
    else:
        while len(questions) <= limit:
            rows = (
                await db.execute(stmt.limit(limit + 1).offset(next_offset))
            ).scalars().all()
            if not rows:
                break
            for index, row in enumerate(rows):
                safe = _safe_question(row)
                if safe is None:
                    continue
                if len(questions) == limit:
                    has_more = True
                    next_offset += index
                    break
                questions.append(safe)
            if has_more or len(rows) < limit + 1:
                if not has_more:
                    next_offset += len(rows)
                break
            next_offset += len(rows)
    return PracticeQuestionSet(
        mode=mode,
        questions=questions[:limit],
        has_more=has_more and mode != "random",
        next_offset=next_offset,
    )


@router.post("/answers", response_model=PracticeAnswerResult)
async def submit_practice_answer(
    *,
    db: deps.SessionDep,
    submission: PracticeAnswerSubmit,
    current_user: User = Depends(deps.get_current_active_user),
) -> PracticeAnswerResult:
    if submission.mode not in _VALID_MODES:
        raise HTTPException(status_code=422, detail="Unsupported practice mode")

    result = await db.execute(
        select(Question).where(
            Question.id == submission.question_id,
            Question.subject_id == submission.subject_id,
            Question.status == QuestionStatus.PUBLISHED.value,
            Question.deleted_at.is_(None),
            Question.parent_id.is_(None),
            visible_questions_filter(current_user),
        )
    )
    question = result.scalar_one_or_none()
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    if question.answer is None:
        raise HTTPException(status_code=422, detail="Question has no answer")

    if question.q_type == QuestionType.FREE_RESPONSE:
        if submission.self_assessed is None:
            raise HTTPException(status_code=422, detail="Self-assessment is required")
        is_correct: bool | None = submission.self_assessed
        score: float | None = float(submission.self_assessed)
        requires_self_assessment = True
    else:
        is_correct, score, requires_self_assessment = _grade_answer(
            question, submission.answer
        )
        if requires_self_assessment:
            raise HTTPException(status_code=422, detail="Answer cannot be graded automatically")

    db.add(
        PracticeAttempt(
            user_id=current_user.id,
            question_id=question.id,
            subject_id=question.subject_id,
            mode=submission.mode,
            submitted_answer=submission.answer,
            is_correct=is_correct,
            score=score,
        )
    )
    await db.commit()

    correct_answer = parse_json_field(question.answer)
    analysis = parse_json_field(question.analysis)
    return PracticeAnswerResult(
        question_id=question.id,
        is_correct=is_correct,
        score=score,
        requires_self_assessment=requires_self_assessment,
        correct_answer=correct_answer if isinstance(correct_answer, dict) else None,
        analysis=analysis if isinstance(analysis, dict) else None,
    )
