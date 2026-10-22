"""抽取策略:AIExtractor(provider 配置 → prompt → 抽取 → KP 富化 → temp_id)。

产出"legacy 字符串形态"的 dict 列表(RawQuestion),喂给归一化漏斗;不产出 v2。
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Optional, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.ai import AIQuestion
from app.services.ai_provider import get_ai_provider
from app.services.structured_parser import parse_local

from .enrich import KnowledgePointEnricher
from .contracts import ExtractionResult
from .image_mask import mask_images, restore_images
from .prompt import PromptBuilder
from .provider_config import resolve_active_provider

logger = logging.getLogger(__name__)


@dataclass
class ScoreDetails:
    per_question: list[float]
    quality: float
    coverage: float
    raw_coverage: float
    expected_count: int
    extracted_count: int
    combined: float


class ExtractionStrategy(Protocol):
    """把归一化前的"原始内容 → 题目 + 整卷结构"抽象成可插拔策略。"""

    async def extract(
        self,
        content: str,
        db: AsyncSession,
        *,
        image_data: bytes | None = None,
        filename: str | None = None,
        mode: str = "extract",
        subject_id: Optional[int] = None,
    ) -> ExtractionResult: ...



def _assign_temp_ids(items: list[dict], parent_temp_id: Optional[str] = None) -> list[dict]:
    """给抽取结果分配临时 id 并递归处理材料题 children 的 parent_id。"""
    processed = []
    for item in items:
        if "id" not in item or not item["id"]:
            item["id"] = str(uuid.uuid4())
        if parent_temp_id:
            item["parent_id"] = parent_temp_id
        if item.get("children"):
            item["children"] = _assign_temp_ids(item["children"], item["id"])
        processed.append(item)
    return processed


class AIExtractor:
    def __init__(
        self,
        prompt_builder: Optional[PromptBuilder] = None,
        enricher: Optional[KnowledgePointEnricher] = None,
    ) -> None:
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.enricher = enricher or KnowledgePointEnricher()

    async def extract(
        self,
        content: str,
        db: AsyncSession,
        *,
        image_data: bytes | None = None,
        filename: str | None = None,
        mode: str = "extract",
        subject_id: Optional[int] = None,
    ) -> ExtractionResult:
        provider_name, config = await resolve_active_provider(db, is_vision=bool(image_data))
        if provider_name is None:
            logger.warning("No active AI provider configuration found.")
            return ExtractionResult()

        config["AI_EXTRACT_PROMPT"] = await self.prompt_builder.build(
            db, mode=mode, subject_id=subject_id
        )

        provider = get_ai_provider(provider_name)

        # 视觉抽取没有 markdown 文本可遮罩;文本抽取才需要把图片 token 换成占位符再喂给 AI。
        masked_content = content
        image_map: dict[str, str] = {}
        if not image_data and content:
            masked_content, image_map = mask_images(content)

        final_content = masked_content
        if filename:
            final_content = f"文件名: {filename}\n\n{masked_content}"

        try:
            questions = await provider.extract_questions(final_content, image_data, config)
            # 文本路径无论是否遮罩到图片都跑还原,以清掉 AI 凭空写出的裸露占位符;视觉路径不涉及。
            if not image_data:
                questions = self._restore_images(questions, image_map)
            await self.enricher.enrich(
                questions, subject_id=subject_id, provider=provider, config=config
            )
            extracted = [q.model_dump() for q in questions]
            return ExtractionResult(questions=_assign_temp_ids(extracted))
        except Exception as e:
            logger.error(f"AI Provider error: {e}")
            raise

    @staticmethod
    def _restore_images(
        questions: list[AIQuestion], image_map: dict[str, str]
    ) -> list[AIQuestion]:
        """把 AI 返回题目里的 @@IMGn@@ 占位符换回真实图片 token(容忍编号写错)，并记录异常。"""
        dumped = [q.model_dump() for q in questions]
        restored, dropped, unresolved = restore_images(dumped, image_map)
        if dropped:
            logger.warning(
                "AI extraction referenced %d more image placeholder(s) than exist; extras stripped",
                dropped,
            )
        if unresolved:
            logger.warning(
                "AI extraction result is missing %d/%d image placeholder(s)",
                unresolved, len(image_map),
            )
        return [AIQuestion(**item) for item in restored]


class TemplateExtractor:
    """确定性本地解析:支持显式标签模板与常见题号、选项、答案格式。"""

    async def extract(
        self,
        content: str,
        db: AsyncSession,
        *,
        image_data: bytes | None = None,
        filename: str | None = None,
        mode: str = "extract",
        subject_id: Optional[int] = None,
    ) -> ExtractionResult:
        return parse_local(content)


class MultiStrategyExtractor:
    """Prefer deterministic parsing and fall back to AI only when structure is weak."""

    _QUESTION_BOUNDARY_RE = re.compile(
        r"(?m)^\s*(?:\*\*)?\(?\d+(?:\.\d+)*\)?[.、．)]\s*\S"
    )
    _TAG_BOUNDARY_RE = re.compile(r"(?m)^\s*(?:\d+[.、．)]\s*)?[【\[]\s*(?:题目|题干|question|title)\s*[】\]]", re.I)
    _CONTAMINATED_CONTENT_RE = re.compile(
        r"(?im)^\s*(?:\*\*)?(?:参考答案|正确答案|答案|解析|详解|解答)\s*[:：]"
        r"|^\s*\*\*[A-Z]\s*[.、．)]\*\*"
    )

    def __init__(
        self,
        local_extractor: Optional[ExtractionStrategy] = None,
        ai_extractor: Optional[ExtractionStrategy] = None,
        *,
        confidence_threshold: float = 0.75,
    ) -> None:
        self.local_extractor = local_extractor or TemplateExtractor()
        self.ai_extractor = ai_extractor or AIExtractor()
        self.confidence_threshold = confidence_threshold

    async def extract(
        self,
        content: str,
        db: AsyncSession,
        *,
        image_data: bytes | None = None,
        filename: str | None = None,
        mode: str = "extract",
        subject_id: Optional[int] = None,
    ) -> ExtractionResult:
        started = time.perf_counter()
        if mode != "extract" or image_data:
            result = await self.ai_extractor.extract(
                content,
                db,
                image_data=image_data,
                filename=filename,
                mode=mode,
                subject_id=subject_id,
            )
            try:
                details = self._score_details(result, content)
            except Exception:
                logger.warning("Could not calculate AI extraction diagnostics", exc_info=True)
                return result
            result.diagnostics = {
                "local_details": None,
                "ai_details": asdict(details),
                "ai_called": True,
                "chosen_strategy": "ai",
                "threshold": self.confidence_threshold,
                "latency_ms": min(int((time.perf_counter() - started) * 1000), 600_000),
                "questions": result.questions,
            }
            return result

        local_result = await self.local_extractor.extract(
            content,
            db,
            filename=filename,
            mode=mode,
            subject_id=subject_id,
        )
        local_details = self._score_details(local_result, content)
        local_score = local_details.combined
        if local_score >= self.confidence_threshold:
            local_result.diagnostics = {
                "local_details": asdict(local_details),
                "ai_details": None,
                "ai_called": False,
                "chosen_strategy": "rule",
                "threshold": self.confidence_threshold,
                "latency_ms": min(int((time.perf_counter() - started) * 1000), 600_000),
                "questions": local_result.questions,
            }
            return local_result

        ai_result = await self.ai_extractor.extract(
            content,
            db,
            filename=filename,
            mode=mode,
            subject_id=subject_id,
        )
        ai_details = self._score_details(ai_result, content)
        chosen_result = ai_result if ai_details.combined > local_score else local_result
        chosen_result.diagnostics = {
            "local_details": asdict(local_details),
            "ai_details": asdict(ai_details),
            "ai_called": True,
            "chosen_strategy": "ai" if chosen_result is ai_result else "rule",
            "threshold": self.confidence_threshold,
            "latency_ms": min(int((time.perf_counter() - started) * 1000), 600_000),
            "questions": chosen_result.questions,
        }
        return chosen_result

    @classmethod
    def _score(cls, result: ExtractionResult, content: str) -> float:
        return cls._score_details(result, content).combined

    @classmethod
    def _score_details(cls, result: ExtractionResult, content: str) -> ScoreDetails:
        questions = result.questions
        if not questions:
            return ScoreDetails([], 0.0, 0.0, 0.0, 0, 0, 0.0)

        question_scores: list[float] = []
        for question in questions:
            score = 0.45 if str(question.get("content") or "").strip() else 0.0
            q_type = question.get("q_type")
            options = question.get("options") or []
            answer = question.get("answer")
            has_answer = bool(answer)
            if q_type in {"single_choice", "multiple_choice"}:
                score += 0.3 if len(options) >= 2 else 0.0
                score += 0.2 if has_answer else 0.0
            elif q_type == "true_false":
                score += 0.35 if has_answer else 0.0
            else:
                score += 0.35 if has_answer else 0.0
            if not cls._CONTAMINATED_CONTENT_RE.search(str(question.get("content") or "")):
                score += 0.05
            question_scores.append(score)

        quality = sum(question_scores) / len(question_scores)
        expected_count = max(
            len(cls._QUESTION_BOUNDARY_RE.findall(content)),
            len(cls._TAG_BOUNDARY_RE.findall(content)),
        )
        raw_coverage = len(questions) / expected_count if expected_count else 1.0
        coverage = min(raw_coverage, 1.0)
        return ScoreDetails(
            per_question=question_scores,
            quality=quality,
            coverage=coverage,
            raw_coverage=raw_coverage,
            expected_count=expected_count,
            extracted_count=len(questions),
            combined=quality * 0.65 + coverage * 0.35,
        )
