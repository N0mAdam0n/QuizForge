"""统一归一化出口:legacy raw dict → 严格 v2 QuestionCreate → 落库。

worker(异步批量)与 `/questions/batch-legacy`(同步复核)共用本模块,消除两处
"adapt → build QuestionCreate → create_question" 循环的行为漂移。

归一化仍走单一漏斗 `adapt_legacy_question`(→ question_content_converter),不重写规则。
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional, Sequence

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas
from app.models.question import QuestionStatus, QuestionType
from app.services.question_legacy_adapter import (
    LegacyQuestionError,
    adapt_legacy_question,
)
from app.services.question_service import question_service

from .qtype_utils import is_tf_answer, is_tf_option_pair, is_tf_type_keyword, resolve_tf_answer
from .contracts import FailedItem, ImportDefaults, NormalizeReport

logger = logging.getLogger(__name__)


def coerce_q_type(raw: Any) -> QuestionType:
    if isinstance(raw, QuestionType):
        return raw
    if raw is None or not str(raw).strip():
        return QuestionType.SINGLE_CHOICE
    s = str(raw).strip().lower()
    try:
        return QuestionType(s)
    except ValueError:
        pass
    if "multiple" in s or "多选" in s:
        return QuestionType.MULTIPLE_CHOICE
    if is_tf_type_keyword(s):
        return QuestionType.TRUE_FALSE
    if "fill" in s or "blank" in s or "填空" in s:
        return QuestionType.FILL_IN_THE_BLANK
    if "free" in s or "response" in s or "essay" in s or "解答" in s or "简答" in s or "short" in s:
        return QuestionType.FREE_RESPONSE
    if "single" in s or "单选" in s or "选择" in s or "choice" in s:
        return QuestionType.SINGLE_CHOICE
    logger.warning("coerce_q_type: unrecognized q_type %r, falling back to single_choice", raw)
    return QuestionType.SINGLE_CHOICE


def apply_true_false_safety_net(
    q_type: QuestionType, options: Any, answer: Any
) -> tuple[QuestionType, Any, Any]:
    """选择题若实为判断题(对/错选项对,或无选项且答案为对/错),改判为 TRUE_FALSE。

    返回 (q_type, options, answer);改判时丢弃选项、把答案换成 "对"/"错" 原文,
    交由 convert_answer(_parse_true_false)转换为布尔值。
    """
    if q_type not in (QuestionType.SINGLE_CHOICE, QuestionType.MULTIPLE_CHOICE):
        return q_type, options, answer
    opts = options if isinstance(options, list) else []
    if opts and is_tf_option_pair(opts):
        new_answer = resolve_tf_answer(answer, opts)
        if answer not in (None, "") and new_answer is None:
            # 答案无法映射为对/错,保留原文交下游降级 legacy_unresolved。
            new_answer = answer
        logger.info("import: reclassify %s with T/F option pair as true_false", q_type.value)
        return QuestionType.TRUE_FALSE, None, new_answer
    if not opts and is_tf_answer(answer):
        logger.info("import: reclassify optionless %s with T/F answer as true_false", q_type.value)
        return QuestionType.TRUE_FALSE, None, resolve_tf_answer(answer) or answer
    return q_type, options, answer


def _coerce_status(raw: Any, default: QuestionStatus) -> QuestionStatus:
    if isinstance(raw, QuestionStatus):
        return raw
    if raw is None:
        return default
    try:
        return QuestionStatus(str(raw))
    except ValueError:
        return default


def coerce_kp_ids(raw: Any) -> list[int]:
    if not raw:
        return []
    out: list[int] = []
    for v in raw:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def _resolve_ai_tags(raw: Mapping[str, Any]) -> Optional[dict]:
    existing = raw.get("ai_suggested_tags")
    if existing:
        return existing
    tags = raw.get("tags")
    if tags:
        return {"ai_extracted": tags}
    return None


class QuestionImporter:
    async def import_batch(
        self,
        db: AsyncSession,
        raws: Sequence[Mapping[str, Any]],
        *,
        user_id: Optional[int],
        import_task_id: Optional[int],
        defaults: ImportDefaults,
    ) -> NormalizeReport:
        """逐题归一化并落库;无法解析/校验失败的题按条记入 failed,不中断整批。"""
        report = NormalizeReport()

        for index, raw in enumerate(raws):
            q_type = coerce_q_type(raw.get("q_type", raw.get("type")))
            q_type, raw_options, raw_answer = apply_true_false_safety_net(
                q_type, raw.get("options"), raw.get("answer")
            )
            status = _coerce_status(raw.get("status"), defaults.status)

            try:
                v2_fields = adapt_legacy_question(
                    q_type=q_type,
                    status=status,
                    content=raw.get("content"),
                    options=raw_options,
                    answer=raw_answer,
                    thinking=raw.get("thinking"),
                    analysis=raw.get("analysis"),
                    summary=raw.get("summary"),
                )
            except LegacyQuestionError as adapt_err:
                report.failed.append(FailedItem(index=index, message=str(adapt_err)))
                logger.warning("import: skip un-adaptable question #%d: %s", index, adapt_err)
                continue

            subject_id = raw.get("subject_id") or defaults.subject_id
            source = raw.get("source") or defaults.source

            try:
                question_in = schemas.QuestionCreate(
                    content=v2_fields["content"],
                    options=v2_fields["options"],
                    answer=v2_fields["answer"],
                    thinking=v2_fields["thinking"],
                    analysis=v2_fields["analysis"],
                    summary=v2_fields["summary"],
                    q_type=q_type,
                    status=v2_fields["status"],
                    difficulty=raw.get("difficulty", 1) or 1,
                    subject_id=subject_id,
                    knowledge_point_ids=coerce_kp_ids(raw.get("knowledge_point_ids")),
                    tag_ids=raw.get("tag_ids") or [],
                    ai_suggested_tags=_resolve_ai_tags(raw),
                    source=source,
                )
                question = await question_service.create_question(
                    db=db,
                    question_in=question_in,
                    user_id=user_id,
                    import_task_id=import_task_id,
                )
            except (ValueError, ValidationError) as create_err:
                report.failed.append(FailedItem(index=index, message=str(create_err)))
                logger.warning("import: failed to create question #%d: %s", index, create_err)
                continue

            report.created.append(question)

        return report


question_importer = QuestionImporter()
