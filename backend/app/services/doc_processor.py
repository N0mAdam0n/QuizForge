import logging
from pathlib import Path
from typing import BinaryIO, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.importing.extract import (
    AIExtractor,
    ExtractionStrategy,
    MultiStrategyExtractor,
    TemplateExtractor,
)
from app.services.importing.contracts import ExtractionResult
from app.services.importing.ingest import DocxIngestor, ImageIngestor, MarkdownArchiveIngestor, MarkdownIngestor
from app.services.telemetry import telemetry

logger = logging.getLogger(__name__)


def _emit_parse_telemetry(
    extraction: ExtractionResult,
    task_id: str,
    doc_format: str,
    mode: str,
    method: str,
) -> None:
    if mode == "extract" and method == "auto" and extraction.diagnostics:
        telemetry.emit_import_parse(
            task_id=task_id,
            diagnostics=extraction.diagnostics,
            doc_format=doc_format,
        )


class DocProcessor:
    def __init__(self):
        self.client = None
        self._ai_extractor = AIExtractor()
        self._template_extractor = TemplateExtractor()
        self._multi_strategy_extractor = MultiStrategyExtractor(
            self._template_extractor, self._ai_extractor
        )
        self._docx_ingestor = DocxIngestor()
        self._markdown_ingestor = MarkdownIngestor()
        self._markdown_archive_ingestor = MarkdownArchiveIngestor()
        self._image_ingestor = ImageIngestor()

    def _extractor_for(self, method: str) -> ExtractionStrategy:
        extractors = {
            "ai": self._ai_extractor,
            "structured": self._template_extractor,
            "auto": self._multi_strategy_extractor,
        }
        try:
            return extractors[method]
        except KeyError as exc:
            raise ValueError(f"Unsupported parsing method: {method}") from exc

    async def process_markdown(self, content: str, db: AsyncSession, filename: str = None, task_id: str = None, mode: str = "extract", method: str = "auto", subject_id: Optional[int] = None) -> dict:
        """
        Process markdown content directly and extract questions.
        
        Args:
            content: Markdown text content
            db: Database session
            filename: Optional filename
            task_id: Optional task ID (if not provided, a new one will be generated)
            mode: Processing mode ("extract" or "solve")
            method: Parsing method ("auto", "ai", or "structured")
        
        Returns:
            Dict with task_id, content, and extracted questions
        """
        doc = await self._markdown_ingestor.ingest(content, task_id=task_id, filename=filename)
        extraction = await self._extractor_for(method).extract(
            doc.markdown, db, filename=doc.filename, mode=mode, subject_id=subject_id
        )
        _emit_parse_telemetry(extraction, doc.task_id, "md", mode, method)
        return {
            "task_id": doc.task_id,
            "content": doc.markdown,
            "questions": extraction.questions,
            "paper": extraction.paper,
        }

    async def process_markdown_archive(self, file_path: Path, db: AsyncSession, task_id: str = None, mode: str = "extract", method: str = "auto", subject_id: Optional[int] = None) -> dict:
        """Extract a markdown archive (zip with local images) and parse questions.

        Local image refs are rewritten to /static/media/{task_id}/... before extraction; multiple
        .md files in the archive are concatenated into one document.
        """
        doc = await self._markdown_archive_ingestor.ingest(file_path, task_id=task_id)
        extraction = await self._extractor_for(method).extract(
            doc.markdown, db, filename=doc.filename, mode=mode, subject_id=subject_id
        )
        _emit_parse_telemetry(extraction, doc.task_id, "md", mode, method)
        return {
            "task_id": doc.task_id,
            "content": doc.markdown,
            "questions": extraction.questions,
            "paper": extraction.paper,
        }

    async def process_image(self, image_file: BinaryIO, db: AsyncSession, task_id: str = None, mode: str = "extract", subject_id: Optional[int] = None) -> dict:
        """
        Process image file and extract questions using Gemini Vision.
        
        Args:
            image_file: Image file object
            db: Database session
            task_id: Optional task ID
            mode: Processing mode ("extract" or "solve")
        
        Returns:
            Dict with task_id, image_url, and extracted questions
        """
        doc = await self._image_ingestor.ingest(image_file, task_id=task_id)
        extraction = await self._multi_strategy_extractor.extract(
            "", db, image_data=doc.image_data, mode=mode, subject_id=subject_id
        )
        _emit_parse_telemetry(extraction, doc.task_id, "image", mode, "auto")
        return {
            "task_id": doc.task_id,
            "image_url": doc.image_url,
            "questions": extraction.questions,
            "paper": extraction.paper,
        }

    async def process_docx(self, file_path: Path, db: AsyncSession = None, task_id: str = None, mode: str = "extract", method: str = "auto", subject_id: Optional[int] = None) -> dict:
        """
        Convert docx to markdown, extract media, and parse questions using Gemini.
        """
        doc = await self._docx_ingestor.ingest(file_path, task_id=task_id)
        extraction = await self._extractor_for(method).extract(
            doc.markdown, db, filename=doc.filename, mode=mode, subject_id=subject_id
        )
        _emit_parse_telemetry(extraction, doc.task_id, "docx", mode, method)
        return {
            "task_id": doc.task_id,
            "content": doc.markdown,
            "questions": extraction.questions,
            "paper": extraction.paper,
        }

doc_processor = DocProcessor()
