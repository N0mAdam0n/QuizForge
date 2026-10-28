import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import case, delete, func, select

from app.api import deps
from app.core.permissions import Permission, can
from app.crud.crud_question import visible_questions_filter
from app.models.import_task import ImportTask
from app.models.practice_attempt import PracticeAttempt
from app.models.question import Question, QuestionStatus, QuestionType, QuestionVisibility
from app.models.user import User
from app.models.wrong_book_entry import WrongBookEntry
from app.schemas.practice import (
    PracticeAnswerResult,
    PracticeAnswerSubmit,
    ManagedQuestionBank,
    PracticeMode,
    PracticeQuestionBank,
    PracticeQuestionBankScopeUpdate,
    PracticeQuestion,
    PracticeQuestionSet,
    WrongBookQuestion,
)
from app.services.question_content import parse_json_field
from app.services.telemetry import telemetry

router = APIRouter()
_VALID_MODES = {"sequential", "random", "type", "wrong", "range"}
_VALID_SCOPES = {"personal", "shared"}
_RANDOM_COUNTS = {"20", "40", "60", "80", "100", "all"}


async def _get_owned_bank(
    db: deps.SessionDep,
    *,
    import_task_id: int,
    subject_id: int,
    scope: str,
    current_user: User,
) -> ImportTask:
    conditions = [
        ImportTask.id == import_task_id,
        ImportTask.scope_type == scope,
        ImportTask.publication_status == "published",
        Question.subject_id == subject_id,
        Question.import_task_id == ImportTask.id,
        visible_questions_filter(current_user),
    ]
    if scope == "personal":
        conditions.append(ImportTask.user_id == current_user.id)
        conditions.append(Question.visibility == QuestionVisibility.PRIVATE.value)
    else:
        conditions.append(Question.visibility == QuestionVisibility.PUBLIC.value)
    result = await db.execute(
        select(ImportTask)
        .join(Question, Question.import_task_id == ImportTask.id)
        .where(*conditions)
        .limit(1)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Question bank not found")
    return task


@router.get("/question-banks", response_model=list[PracticeQuestionBank])
async def read_practice_question_banks(
    db: deps.SessionDep,
    subject_id: int,
    scope: str,
    current_user: User = Depends(deps.get_current_active_user),
) -> list[PracticeQuestionBank]:
    if scope not in _VALID_SCOPES:
        raise HTTPException(status_code=422, detail="Unsupported question-bank scope")
    if scope == "personal":
        scope_filter = ImportTask.user_id == current_user.id
        visibility = QuestionVisibility.PRIVATE.value
    else:
        scope_filter = True
        visibility = QuestionVisibility.PUBLIC.value

    result = await db.execute(
        select(
            ImportTask.id,
            ImportTask.original_filename,
            ImportTask.user_id,
            ImportTask.created_at,
            func.count(func.distinct(Question.id)).label("question_count"),
        )
        .join(Question, Question.import_task_id == ImportTask.id)
        .where(
            ImportTask.scope_type == scope,
            ImportTask.publication_status == "published",
            scope_filter,
            Question.subject_id == subject_id,
            Question.status == QuestionStatus.PUBLISHED.value,
            Question.deleted_at.is_(None),
            Question.parent_id.is_(None),
            Question.answer.is_not(None),
            Question.visibility == visibility,
            visible_questions_filter(current_user),
        )
        .group_by(ImportTask.id, ImportTask.original_filename, ImportTask.created_at)
        .order_by(func.max(Question.created_at).desc(), ImportTask.id.desc())
    )
    return [
        PracticeQuestionBank(
            id=row.id,
            original_filename=row.original_filename,
            scope=scope,
            question_count=row.question_count,
            publication_status="published",
            created_at=row.created_at,
            can_change_scope=(
                row.user_id == current_user.id
                or can(current_user, Permission.MANAGE_SUBJECT, subject_id=subject_id)
            ),
        )
        for row in result
    ]


@router.get("/wrong-book", response_model=list[WrongBookQuestion])
async def read_wrong_book(
    db: deps.SessionDep,
    subject_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(deps.get_current_active_user),
) -> list[WrongBookQuestion]:
    stmt = select(WrongBookEntry).where(WrongBookEntry.user_id == current_user.id)
    if subject_id is not None:
        stmt = stmt.where(WrongBookEntry.subject_id == subject_id)
    stmt = stmt.order_by(WrongBookEntry.last_wrong_at.desc(), WrongBookEntry.id).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    wrong_questions = []
    for entry in rows:
        snapshot = entry.question_snapshot
        wrong_questions.append(
            WrongBookQuestion(
                id=entry.question_id,
                subject_id=entry.subject_id,
                import_task_id=entry.import_task_id,
                original_filename=entry.original_filename,
                content=snapshot["content"],
                q_type=snapshot["q_type"],
                options=snapshot["options"],
                answer=snapshot["answer"],
                analysis=snapshot["analysis"],
                last_wrong_at=entry.last_wrong_at,
                wrong_count=entry.wrong_count,
            )
        )
    return wrong_questions


@router.get("/question-banks/{import_task_id}", response_model=PracticeQuestionBank)
async def read_practice_question_bank(
    *,
    import_task_id: int,
    subject_id: int,
    db: deps.SessionDep,
    current_user: User = Depends(deps.get_current_active_user),
) -> PracticeQuestionBank:
    result = await db.execute(
        select(ImportTask)
        .join(Question, Question.import_task_id == ImportTask.id)
        .where(
            ImportTask.id == import_task_id,
            Question.subject_id == subject_id,
            Question.deleted_at.is_(None),
            visible_questions_filter(current_user),
        )
        .limit(1)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Question bank not found")
    task = row[0]
    if task.scope_type == "personal" and task.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Question bank not found")
    return PracticeQuestionBank(
        id=task.id,
        original_filename=task.original_filename,
        scope=task.scope_type,
        question_count=(await db.scalar(
            select(func.count(Question.id)).where(
                Question.import_task_id == task.id,
                Question.subject_id == subject_id,
                Question.deleted_at.is_(None),
            )
        )) or 0,
        can_change_scope=(
            task.user_id == current_user.id
            or can(current_user, Permission.MANAGE_SUBJECT, subject_id=subject_id)
        ),
        publication_status=task.publication_status,
        created_at=task.created_at,
    )


@router.get("/manage-question-banks", response_model=list[ManagedQuestionBank])
async def read_managed_question_banks(
    db: deps.SessionDep,
    scope: str = "personal",
    subject_id: int | None = None,
    current_user: User = Depends(deps.get_current_active_user),
) -> list[ManagedQuestionBank]:
    if scope not in _VALID_SCOPES:
        raise HTTPException(status_code=422, detail="Unsupported question-bank scope")
    stmt = (
        select(
            ImportTask.id,
            ImportTask.original_filename,
            ImportTask.scope_type,
            ImportTask.publication_status,
            ImportTask.user_id,
            ImportTask.created_at,
            func.count(func.distinct(Question.id)).label("question_count"),
            func.sum(
                case(
                    (Question.status == QuestionStatus.PUBLISHED.value, 1),
                    else_=0,
                )
            ).label("published_count"),
            func.min(Question.subject_id).label("subject_id"),
        )
        .join(Question, Question.import_task_id == ImportTask.id)
        .where(
            ImportTask.scope_type == scope,
            Question.deleted_at.is_(None),
        )
    )
    if scope == "personal":
        stmt = stmt.where(ImportTask.user_id == current_user.id)
    elif not current_user.is_superuser:
        from app.core.permissions import accessible_subject_ids

        subject_ids = accessible_subject_ids(current_user) or set()
        stmt = stmt.where(Question.subject_id.in_(subject_ids))
    if subject_id is not None:
        stmt = stmt.where(Question.subject_id == subject_id)
    stmt = stmt.group_by(
        ImportTask.id,
        ImportTask.original_filename,
        ImportTask.created_at,
        ImportTask.scope_type,
        ImportTask.publication_status,
        ImportTask.user_id,
    ).order_by(ImportTask.created_at.desc(), ImportTask.id.desc())

    result = await db.execute(stmt)
    banks = []
    for row in result:
        can_edit = row.user_id == current_user.id or (
            row.subject_id is not None
            and can(current_user, Permission.MANAGE_SUBJECT, subject_id=row.subject_id)
        )
        banks.append(
            ManagedQuestionBank(
                id=row.id,
                original_filename=row.original_filename,
                scope=row.scope_type,
                publication_status=row.publication_status,
                question_count=row.question_count,
                published_count=row.published_count,
                created_at=row.created_at,
                can_edit=can_edit,
            )
        )
    return banks


@router.get("/manage-question-banks/{import_task_id}", response_model=ManagedQuestionBank)
async def read_managed_question_bank(
    *,
    import_task_id: int,
    subject_id: int,
    db: deps.SessionDep,
    current_user: User = Depends(deps.get_current_active_user),
) -> ManagedQuestionBank:
    result = await db.execute(
        select(ImportTask)
        .join(Question, Question.import_task_id == ImportTask.id)
        .where(
            ImportTask.id == import_task_id,
            Question.subject_id == subject_id,
            Question.deleted_at.is_(None),
            visible_questions_filter(current_user),
        )
        .limit(1)
    )
    task = result.scalars().first()
    if task is None:
        raise HTTPException(status_code=404, detail="Question bank not found")
    can_edit = task.user_id == current_user.id or can(
        current_user, Permission.MANAGE_SUBJECT, subject_id=subject_id
    )
    if task.scope_type == "personal" and task.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Question bank not found")
    if not can_edit:
        raise HTTPException(status_code=403, detail="Not allowed to manage this question bank")
    counts = await db.execute(
        select(
            func.count(Question.id),
            func.count(Question.id).filter(Question.status == QuestionStatus.PUBLISHED.value),
        ).where(
            Question.import_task_id == import_task_id,
            Question.subject_id == subject_id,
            Question.deleted_at.is_(None),
        )
    )
    question_count, published_count = counts.one()
    return ManagedQuestionBank(
        id=task.id,
        original_filename=task.original_filename,
        scope=task.scope_type,
        publication_status=task.publication_status,
        question_count=question_count,
        published_count=published_count,
        created_at=task.created_at,
        can_edit=can_edit,
    )


@router.post("/question-banks/{import_task_id}/publish", response_model=ManagedQuestionBank)
async def publish_personal_question_bank(
    *,
    import_task_id: int,
    db: deps.SessionDep,
    current_user: User = Depends(deps.get_current_active_user),
) -> ManagedQuestionBank:
    task_result = await db.execute(
        select(ImportTask).where(
            ImportTask.id == import_task_id,
            ImportTask.scope_type == "personal",
            ImportTask.user_id == current_user.id,
        )
    )
    task = task_result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Personal question bank not found")
    questions_result = await db.execute(
        select(Question).where(
            Question.import_task_id == import_task_id,
            Question.deleted_at.is_(None),
        )
    )
    questions = questions_result.scalars().all()
    if not questions:
        raise HTTPException(status_code=409, detail="Question bank has no questions")
    for question in questions:
        if question.answer is None:
            question.status = QuestionStatus.DRAFT.value
        else:
            answer = parse_json_field(question.answer)
            if isinstance(answer, dict) and answer.get("kind") != "legacy_unresolved":
                question.status = QuestionStatus.PUBLISHED.value
    task.publication_status = "published"
    await db.commit()
    return ManagedQuestionBank(
        id=task.id,
        original_filename=task.original_filename,
        scope=task.scope_type,
        publication_status=task.publication_status,
        question_count=len(questions),
        published_count=sum(
            question.status == QuestionStatus.PUBLISHED.value for question in questions
        ),
        created_at=task.created_at,
        can_edit=True,
    )


@router.put("/question-banks/{import_task_id}/scope")
async def update_question_bank_scope(
    *,
    import_task_id: int,
    db: deps.SessionDep,
    payload: PracticeQuestionBankScopeUpdate,
    current_user: User = Depends(deps.get_current_active_user),
) -> dict[str, str | int]:
    result = await db.execute(
        select(ImportTask).where(ImportTask.id == import_task_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Question bank not found")
    subject_result = await db.execute(
        select(Question.subject_id)
        .where(
            Question.import_task_id == import_task_id,
            Question.subject_id.is_not(None),
        )
        .distinct()
    )
    subject_ids = subject_result.scalars().all()
    if not subject_ids:
        raise HTTPException(status_code=404, detail="Question bank not found")
    for subject_id in subject_ids:
        if not can(current_user, Permission.EDIT_QUESTION, subject_id=subject_id):
            raise HTTPException(status_code=403, detail="Not allowed to move this question bank")
        if (
            not current_user.is_superuser
            and task.user_id != current_user.id
            and not can(current_user, Permission.MANAGE_SUBJECT, subject_id=subject_id)
        ):
            raise HTTPException(status_code=403, detail="Not allowed to move this question bank")

    new_scope = payload.scope
    if new_scope not in _VALID_SCOPES:
        raise HTTPException(status_code=422, detail="Unsupported question-bank scope")
    if task.scope_type != new_scope:
        questions_result = await db.execute(
            select(Question).where(Question.import_task_id == import_task_id)
        )
        questions = questions_result.scalars().all()
        if any(question.visibility == "group" for question in questions):
            raise HTTPException(
                status_code=409,
                detail="Question banks containing group-restricted questions cannot be moved",
            )
        if new_scope == "personal" and any(
            question.created_by != task.user_id for question in questions
        ):
            raise HTTPException(
                status_code=403,
                detail="Only question banks owned by their original importer can move into a personal space",
            )
        for question in questions:
            question.visibility = (
                QuestionVisibility.PRIVATE.value
                if new_scope == "personal"
                else QuestionVisibility.PUBLIC.value
            )
            if new_scope == "shared" and question.status == QuestionStatus.PUBLISHED.value:
                question.status = QuestionStatus.PENDING.value
                question.review_count = 0
            elif (
                new_scope == "personal"
                and question.status in {
                    QuestionStatus.PENDING.value,
                    QuestionStatus.DRAFT.value,
                }
            ):
                answer = parse_json_field(question.answer)
                if isinstance(answer, dict) and answer.get("kind") != "legacy_unresolved":
                    question.status = QuestionStatus.PUBLISHED.value
        task.scope_type = new_scope
        task.publication_status = "published" if new_scope == "personal" else "pending"
        await db.commit()
    return {"id": task.id, "scope": task.scope_type}


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
        blank_count=(
            len(answer.get("blanks", []))
            if answer.get("kind") == "fill_in_the_blank"
            and isinstance(answer.get("blanks"), list)
            else 0
        ),
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
        return None, None, True
    if answer_kind == "free_response":
        return None, None, True
    return None, None, True


@router.get("/questions", response_model=PracticeQuestionSet)
async def read_practice_questions(
    db: deps.SessionDep,
    subject_id: int,
    scope: str,
    import_task_id: int,
    mode: PracticeMode = "sequential",
    q_type: QuestionType | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    random_count: str = "20",
    start_number: int | None = Query(default=None, ge=1),
    end_number: int | None = Query(default=None, ge=1),
    current_user: User = Depends(deps.get_current_active_user),
) -> PracticeQuestionSet:
    if scope not in _VALID_SCOPES:
        raise HTTPException(status_code=422, detail="Unsupported question-bank scope")
    if mode not in _VALID_MODES:
        raise HTTPException(status_code=422, detail="Unsupported practice mode")
    if mode == "type" and q_type is None:
        raise HTTPException(status_code=422, detail="q_type is required for type practice")
    if mode != "type" and q_type is not None:
        raise HTTPException(status_code=422, detail="q_type is only valid for type practice")
    if mode == "random" and random_count not in _RANDOM_COUNTS:
        raise HTTPException(status_code=422, detail="Unsupported random question count")
    if mode != "random" and random_count != "20":
        raise HTTPException(
            status_code=422,
            detail="random_count is only valid for random practice",
        )
    if mode == "range":
        if start_number is None or end_number is None:
            raise HTTPException(
                status_code=422,
                detail="start_number and end_number are required for range practice",
            )
        if start_number > end_number:
            raise HTTPException(
                status_code=422,
                detail="start_number must not exceed end_number",
            )
    elif start_number is not None or end_number is not None:
        raise HTTPException(
            status_code=422,
            detail="start_number and end_number are only valid for range practice",
        )
    await _get_owned_bank(
        db,
        import_task_id=import_task_id,
        subject_id=subject_id,
        scope=scope,
        current_user=current_user,
    )

    stmt = select(Question).where(
        Question.import_task_id == import_task_id,
        Question.subject_id == subject_id,
        Question.status == QuestionStatus.PUBLISHED.value,
        Question.deleted_at.is_(None),
        Question.parent_id.is_(None),
        Question.answer.is_not(None),
        Question.visibility == (
            QuestionVisibility.PRIVATE.value
            if scope == "personal"
            else QuestionVisibility.PUBLIC.value
        ),
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

    total_count = await db.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ) or 0
    range_offset = 0
    if mode == "range":
        range_offset = start_number - 1
        total_count = max(min(end_number, total_count) - range_offset, 0)

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
        requested_count = (
            total_count if random_count == "all" else int(random_count)
        )
        rows = (await db.execute(stmt.limit(requested_count + 1))).scalars().all()
        for row in rows:
            safe = _safe_question(row)
            if safe is not None:
                questions.append(safe)
            if len(questions) >= requested_count:
                break
    else:
        query_offset = offset + range_offset
        while len(questions) <= limit:
            remaining_count = total_count - next_offset
            if remaining_count <= 0:
                break
            query_limit = min(limit + 1, remaining_count)
            rows = (
                await db.execute(stmt.limit(query_limit).offset(query_offset))
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
            query_offset += len(rows)
    return PracticeQuestionSet(
        mode=mode,
        questions=questions if mode == "random" else questions[:limit],
        total_count=(
            len(questions[:requested_count])
            if mode == "random"
            else total_count
        ),
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

    await _get_owned_bank(
        db,
        import_task_id=submission.import_task_id,
        subject_id=submission.subject_id,
        scope=submission.scope,
        current_user=current_user,
    )
    result = await db.execute(
        select(Question).where(
            Question.id == submission.question_id,
            Question.subject_id == submission.subject_id,
            Question.import_task_id == submission.import_task_id,
            Question.status == QuestionStatus.PUBLISHED.value,
            Question.deleted_at.is_(None),
            Question.parent_id.is_(None),
            Question.visibility == (
                QuestionVisibility.PRIVATE.value
                if submission.scope == "personal"
                else QuestionVisibility.PUBLIC.value
            ),
            visible_questions_filter(current_user),
        )
    )
    question = result.scalar_one_or_none()
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    if question.answer is None:
        raise HTTPException(status_code=422, detail="Question has no answer")

    if submission.dont_know:
        is_correct: bool | None = False
        score: float | None = 0.0
        requires_self_assessment = True
    else:
        is_correct, score, requires_self_assessment = _grade_answer(
            question, submission.answer
        )
        if requires_self_assessment:
            if submission.self_assessed is None:
                raise HTTPException(status_code=422, detail="Self-assessment is required")
            is_correct = submission.self_assessed
            score = float(submission.self_assessed)

    if is_correct is False:
        content = parse_json_field(question.content)
        correct_answer = parse_json_field(question.answer)
        analysis_snapshot = parse_json_field(question.analysis)
        if not isinstance(content, dict) or not isinstance(correct_answer, dict):
            raise HTTPException(status_code=500, detail="Question content or answer is invalid")
        original_filename = None
        if question.import_task_id is not None:
            task = await db.get(ImportTask, question.import_task_id)
            if task is not None:
                original_filename = task.original_filename
        snapshot = {
            "content": content,
            "q_type": question.q_type.value,
            "options": question.options or [],
            "answer": correct_answer,
            "analysis": analysis_snapshot if isinstance(analysis_snapshot, dict) else None,
        }
        now = datetime.utcnow()
        values = {
            "user_id": current_user.id,
            "question_id": question.id,
            "subject_id": question.subject_id,
            "import_task_id": question.import_task_id,
            "original_filename": original_filename,
            "question_snapshot": snapshot,
            "wrong_count": 1,
            "first_wrong_at": now,
            "last_wrong_at": now,
        }
        dialect_name = db.bind.dialect.name if db.bind is not None else ""
        if dialect_name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as dialect_insert

            statement = dialect_insert(WrongBookEntry).values(**values)
            statement = statement.on_conflict_do_update(
                index_elements=["user_id", "question_id"],
                set_={
                    "wrong_count": WrongBookEntry.wrong_count + 1,
                    "last_wrong_at": now,
                    "question_snapshot": snapshot,
                    "subject_id": question.subject_id,
                    "import_task_id": question.import_task_id,
                    "original_filename": original_filename,
                },
            )
            await db.execute(statement)
        elif dialect_name == "mysql":
            from sqlalchemy.dialects.mysql import insert as dialect_insert

            statement = dialect_insert(WrongBookEntry).values(**values)
            statement = statement.on_duplicate_key_update(
                wrong_count=WrongBookEntry.wrong_count + 1,
                last_wrong_at=now,
                question_snapshot=snapshot,
                subject_id=question.subject_id,
                import_task_id=question.import_task_id,
                original_filename=original_filename,
            )
            await db.execute(statement)
        else:
            existing_entry = await db.scalar(
                select(WrongBookEntry).where(
                    WrongBookEntry.user_id == current_user.id,
                    WrongBookEntry.question_id == question.id,
                )
            )
            if existing_entry is None:
                db.add(WrongBookEntry(**values))
            else:
                existing_entry.wrong_count += 1
                existing_entry.last_wrong_at = now
                existing_entry.question_snapshot = snapshot
                existing_entry.subject_id = question.subject_id
                existing_entry.import_task_id = question.import_task_id
                existing_entry.original_filename = original_filename

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

    telemetry.emit_practice_answer(
        question_id=question.id,
        question_type=question.q_type.value,
        correct=is_correct,
        time_ms=submission.time_ms,
        session_id=submission.session_id,
    )

    correct_answer = parse_json_field(question.answer)
    analysis = parse_json_field(question.analysis)
    return PracticeAnswerResult(
        question_id=question.id,
        is_correct=is_correct,
        score=score,
        requires_self_assessment=requires_self_assessment,
        correct_answer=correct_answer if isinstance(correct_answer, dict) else None,
        analysis=analysis if isinstance(analysis, dict) else None,
        dont_know=submission.dont_know,
    )


_HISTORY_FIELDS = ["id", "question_id", "subject_id", "mode", "submitted_answer", "is_correct", "score", "created_at"]


@router.get("/history/export")
async def export_my_practice_history(
    db: deps.SessionDep,
    format: str = Query("csv", pattern="^(csv|json)$"),
    current_user: User = Depends(deps.get_current_active_user),
) -> Response:
    """导出当前用户自己的作答记录（只含本人数据）。"""
    rows = (await db.execute(
        select(PracticeAttempt).where(PracticeAttempt.user_id == current_user.id)
        .order_by(PracticeAttempt.id)
    )).scalars().all()
    records = [
        {
            "id": r.id,
            "question_id": r.question_id,
            "subject_id": r.subject_id,
            "mode": r.mode,
            "submitted_answer": r.submitted_answer,
            "is_correct": r.is_correct,
            "score": r.score,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    if format == "json":
        return Response(
            json.dumps(records, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=practice-history.json"},
        )
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_HISTORY_FIELDS)
    writer.writeheader()
    for record in records:
        writer.writerow({**record, "submitted_answer": json.dumps(record["submitted_answer"], ensure_ascii=False)})
    return Response(
        "\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=practice-history.csv"},
    )


@router.delete("/history")
async def clear_my_practice_history(
    db: deps.SessionDep,
    confirm: str = Query(..., description="must be CLEAR"),
    current_user: User = Depends(deps.get_current_active_user),
) -> dict[str, int]:
    """清空当前用户自己的作答记录；错题本不受影响。"""
    if confirm != "CLEAR":
        raise HTTPException(status_code=400, detail="需要确认")
    result = await db.execute(delete(PracticeAttempt).where(PracticeAttempt.user_id == current_user.id))
    await db.commit()
    return {"deleted": result.rowcount or 0}
