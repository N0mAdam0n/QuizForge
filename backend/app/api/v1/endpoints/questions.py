from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app import crud, schemas, models
from app.api import deps
from app import capabilities
from app.capabilities import questions as question_caps
from app.crud.crud_question import is_question_visible
from app.models.question import QuestionType, QuestionStatus
from app.models.import_task import ImportTask, ImportTaskStatus
from app.services.importing.contracts import ImportDefaults
from app.services.importing.normalize import question_importer
from app.services.telemetry import telemetry

router = APIRouter()


def _question_review_fields(before: Any, after: Any) -> list[str]:
    fields: list[str] = []
    for source, target in (
        ("content", "content"),
        ("options", "options"),
        ("answer", "answer"),
        ("analysis", "analysis"),
        ("q_type", "q_type"),
        ("difficulty", "difficulty"),
    ):
        old_value = before.get(source) if isinstance(before, dict) else getattr(before, source, None)
        new_value = getattr(after, target, None)
        if hasattr(old_value, "value"):
            old_value = old_value.value
        if hasattr(new_value, "value"):
            new_value = new_value.value
        if isinstance(old_value, str) and source in {"content", "answer", "analysis"}:
            try:
                import json

                old_value = json.loads(old_value)
            except (ValueError, TypeError):
                pass
        if isinstance(new_value, str) and source in {"content", "answer", "analysis"}:
            try:
                import json

                new_value = json.loads(new_value)
            except (ValueError, TypeError):
                pass
        if old_value != new_value:
            fields.append(target)
    return fields


def _question_snapshot(question: Any) -> dict[str, Any]:
    return {
        field: getattr(question, field, None)
        for field in ("content", "options", "answer", "analysis", "q_type", "difficulty", "source")
    }


def _review_category(fields: list[str]) -> str:
    if "answer" in fields:
        return "answer_fix"
    if "options" in fields:
        return "option_fix"
    if "q_type" in fields:
        return "type_fix"
    if "content" in fields or "analysis" in fields:
        return "format"
    return "other"


@router.get("", response_model=schemas.QuestionPage)
async def read_questions(
    db: deps.SessionDep,
    page: int = 1,
    size: int = 10,
    subject_id: Optional[int] = None,
    knowledge_point_ids: List[int] = Query(None),
    tag_ids: List[int] = Query(None),
    q_type: Optional[QuestionType] = None,
    difficulty: Optional[int] = None,
    status: Optional[str] = None,
    import_task_id: Optional[int] = None,
    import_task_name: Optional[str] = None,
    review_count: Optional[int] = None,
    creator_id: Optional[int] = None,
    reviewer_id: Optional[int] = None,
    keyword: Optional[str] = None,
    id: Optional[int] = None,
    ids: List[int] = Query(None),
    source: Optional[str] = None,
    root_only: bool = False,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    skip = (page - 1) * size
    questions = await crud.question.get_multi_with_filters(
        db, 
        skip=skip, 
        limit=size,
        subject_id=subject_id,
        knowledge_point_ids=knowledge_point_ids,
        tag_ids=tag_ids,
        q_type=q_type,
        difficulty=difficulty,
        status=status,
        import_task_id=import_task_id,
        import_task_name=import_task_name,
        review_count=review_count,
        creator_id=creator_id,
        reviewer_id=reviewer_id,
        keyword=keyword,
        id=id,
        ids=ids,
        source=source,
        root_only=root_only,
        viewer=current_user
    )
    total = await crud.question.count_with_filters(
        db,
        subject_id=subject_id,
        knowledge_point_ids=knowledge_point_ids,
        tag_ids=tag_ids,
        q_type=q_type,
        difficulty=difficulty,
        status=status,
        import_task_id=import_task_id,
        import_task_name=import_task_name,
        review_count=review_count,
        creator_id=creator_id,
        reviewer_id=reviewer_id,
        keyword=keyword,
        id=id,
        ids=ids,
        source=source,
        root_only=root_only,
        viewer=current_user
    )
    
    import math
    return {
        "items": questions,
        "total": total,
        "page": page,
        "size": size,
        "pages": math.ceil(total / size) if size > 0 else 0
    }

@router.post("", response_model=schemas.Question)
async def create_question(
    *,
    db: deps.SessionDep,
    question_in: schemas.QuestionCreate,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await capabilities.run(
        "question.create", deps.api_context(db, current_user), question_in
    )

@router.post("/batch", response_model=List[schemas.Question])
async def create_questions_batch(
    *,
    db: deps.SessionDep,
    batch_in: schemas.QuestionBatchCreate,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await capabilities.run(
        "question.batch_create", deps.api_context(db, current_user), batch_in
    )

@router.post("/batch-legacy", response_model=schemas.LegacyBatchResult)
async def create_questions_batch_legacy(
    *,
    db: deps.SessionDep,
    batch_in: schemas.LegacyQuestionBatchCreate,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """智能导入工作台专用:接收旧字符串形态题目,后端统一经 adapter 转严格 v2 后落库。

    严格 QuestionCreate 不接受旧格式;前端不复制 Python 解析规则。无法解析的答案不静默
    写入 legacy_unresolved,而是按条上报到 failed。
    """
    if not batch_in.questions:
        return schemas.LegacyBatchResult()

    import_task = ImportTask(
        user_id=current_user.id,
        description=batch_in.filename or f"Batch import of {len(batch_in.questions)} questions",
        source="smart_import",
        file_path=batch_in.file_path or "virtual",
        original_filename=batch_in.filename or "smart_import.json",
        file_type="json",
        status=ImportTaskStatus.COMPLETED,
    )
    db.add(import_task)
    await db.commit()
    await db.refresh(import_task)

    raws = [item.model_dump() for item in batch_in.questions]
    defaults = ImportDefaults(
        subject_id=current_user.last_active_subject_id,
        status=QuestionStatus.PENDING,
        source=batch_in.filename,
    )
    report = await question_importer.import_batch(
        db,
        raws,
        user_id=current_user.id,
        import_task_id=import_task.id,
        defaults=defaults,
    )

    return schemas.LegacyBatchResult(
        import_task_id=import_task.id,
        created=report.created,
        failed=[
            schemas.LegacyBatchError(index=f.index, message=f.message)
            for f in report.failed
        ],
    )

@router.get("/{id}", response_model=schemas.Question)
async def read_question(
    *,
    db: deps.SessionDep,
    id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    question = await crud.question.get(db=db, id=id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    if not is_question_visible(question, current_user):
        raise HTTPException(status_code=404, detail="Question not found")
    return question

@router.put("/{id}", response_model=schemas.Question)
async def update_question(
    *,
    db: deps.SessionDep,
    id: int,
    question_in: schemas.QuestionUpdate,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    before_question = await crud.question.get(db=db, id=id)
    before = _question_snapshot(before_question) if before_question is not None else None
    updated = await capabilities.run(
        "question.update",
        deps.api_context(db, current_user),
        question_caps.QuestionUpdateInput(id=id, data=question_in),
    )
    if before is not None:
        changed = _question_review_fields(before, updated)
        if "tag_ids" in question_in.model_fields_set:
            changed.append("tags")
        if before["source"] != getattr(updated, "source", None):
            changed.append("other")
        telemetry.emit_review_edit(
            question_id=id,
            import_task_id=getattr(updated, "import_task_id", None),
            fields_changed=changed,
            accepted_unchanged=not changed,
            edit_category=_review_category(changed),
        )
    return updated

@router.post("/{id}/review", response_model=schemas.Question)
async def review_question(
    *,
    db: deps.SessionDep,
    id: int,
    review_in: schemas.QuestionReview,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    before = await crud.question.get(db=db, id=id)
    updated = await capabilities.run(
        "question.review",
        deps.api_context(db, current_user),
        question_caps.QuestionReviewInput(id=id, data=review_in),
    )
    if before is not None:
        accepted = review_in.action == "approve"
        telemetry.emit_review_edit(
            question_id=id,
            import_task_id=getattr(updated, "import_task_id", None),
            fields_changed=[] if accepted else ["other"],
            accepted_unchanged=accepted,
            edit_category="other",
        )
    return updated

@router.delete("/{id}", response_model=schemas.Question)
async def delete_question(
    *,
    db: deps.SessionDep,
    id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    before = await crud.question.get(db=db, id=id)
    deleted = await capabilities.run(
        "question.delete",
        deps.api_context(db, current_user),
        question_caps.QuestionIdInput(id=id),
    )
    if before is not None and before.deleted_at is None:
        telemetry.emit_review_edit(
            question_id=id,
            import_task_id=getattr(deleted, "import_task_id", None),
            fields_changed=["other"],
            accepted_unchanged=False,
            edit_category="delete",
        )
    return deleted

@router.post("/batch-delete", response_model=Any)
async def delete_questions_batch(
    *,
    db: deps.SessionDep,
    delete_data: schemas.QuestionBatchDelete,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    was_deleted = {}
    for question_id in delete_data.ids:
        question = await db.get(models.Question, question_id)
        was_deleted[question_id] = question is None or question.deleted_at is not None
    result = await capabilities.run(
        "question.batch_delete", deps.api_context(db, current_user), delete_data
    )
    for question_id in delete_data.ids:
        question = await db.get(models.Question, question_id)
        if question is not None and not was_deleted[question_id] and question.deleted_at is not None:
            telemetry.emit_review_edit(
                question_id=question_id,
                import_task_id=question.import_task_id,
                fields_changed=["other"],
                accepted_unchanged=False,
                edit_category="delete",
            )
    return result

@router.post("/batch-update", response_model=Any)
async def update_questions_batch(
    *,
    db: deps.SessionDep,
    update_data: schemas.QuestionBatchUpdate,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    before: dict[int, tuple[Optional[str], Optional[int], Optional[int]]] = {}
    for question_id in update_data.ids:
        question = await db.get(models.Question, question_id)
        if question is not None:
            before[question_id] = (
                question.source,
                question.import_task_id,
                question.created_by,
            )
    result = await capabilities.run(
        "question.batch_update", deps.api_context(db, current_user), update_data
    )
    for question_id, (old_source, import_task_id, created_by) in before.items():
        if (
            old_source != update_data.source
            and update_data.source is not None
            and (current_user.is_superuser or created_by == current_user.id)
        ):
            telemetry.emit_review_edit(
                question_id=question_id,
                import_task_id=import_task_id,
                fields_changed=["other"],
                accepted_unchanged=False,
                edit_category="other",
            )
    return result

@router.post("/batch-confirm", response_model=Any)
async def batch_confirm_questions(
    *,
    db: deps.SessionDep,
    confirm_data: schemas.QuestionBatchConfirm,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    initial_status = {}
    for question_id in confirm_data.question_ids:
        question = await db.get(models.Question, question_id)
        initial_status[question_id] = question.status if question is not None else None
    result = await capabilities.run(
        "question.batch_confirm", deps.api_context(db, current_user), confirm_data
    )
    if result.get("processed_count", 0):
        for question_id in confirm_data.question_ids:
            question = await db.get(models.Question, question_id)
            if question is None or initial_status.get(question_id) != QuestionStatus.DRAFT:
                continue
            if confirm_data.action == "approve":
                telemetry.emit_review_edit(
                    question_id=question_id,
                    import_task_id=question.import_task_id,
                    fields_changed=[],
                    accepted_unchanged=True,
                    edit_category="other",
                )
            elif question.deleted_at is not None:
                telemetry.emit_review_edit(
                    question_id=question_id,
                    import_task_id=question.import_task_id,
                    fields_changed=["other"],
                    accepted_unchanged=False,
                    edit_category="delete",
                )
    return result
