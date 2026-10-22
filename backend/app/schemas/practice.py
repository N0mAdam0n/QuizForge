from typing import Any, Literal, Optional

from pydantic import BaseModel, Field
from datetime import datetime

from app.models.question import QuestionType


PracticeMode = Literal["sequential", "random", "type", "wrong", "range"]
PracticeScope = Literal["personal", "shared"]


class PracticeOption(BaseModel):
    id: str
    label: str
    content: Optional[dict[str, Any]] = None


class PracticeQuestion(BaseModel):
    id: int
    content: dict[str, Any]
    q_type: QuestionType
    options: list[PracticeOption] = Field(default_factory=list)
    difficulty: int
    blank_count: int = 0


class PracticeQuestionSet(BaseModel):
    mode: PracticeMode
    questions: list[PracticeQuestion]
    total_count: int = 0
    has_more: bool = False
    next_offset: int = 0


class PracticeQuestionBank(BaseModel):
    id: int
    original_filename: str
    scope: PracticeScope
    question_count: int
    can_change_scope: bool = False
    publication_status: Literal["pending", "published"] = "published"
    created_at: datetime


class ManagedQuestionBank(BaseModel):
    id: int
    original_filename: str
    scope: PracticeScope
    publication_status: Literal["pending", "published"]
    question_count: int
    published_count: int
    created_at: datetime
    can_edit: bool


class PracticeQuestionBankScopeUpdate(BaseModel):
    scope: Literal["personal", "shared"]


class PracticeAnswerSubmit(BaseModel):
    question_id: int
    subject_id: int
    scope: PracticeScope
    import_task_id: int
    mode: PracticeMode
    answer: Any = None
    self_assessed: Optional[bool] = None
    dont_know: bool = False
    time_ms: Optional[int] = Field(default=None, ge=0, le=3_600_000)
    session_id: Optional[str] = Field(default=None, max_length=64)


class PracticeAnswerResult(BaseModel):
    question_id: int
    is_correct: Optional[bool]
    score: Optional[float]
    requires_self_assessment: bool = False
    correct_answer: Optional[dict[str, Any]] = None
    analysis: Optional[dict[str, Any]] = None
    dont_know: bool = False


class WrongBookQuestion(BaseModel):
    id: int
    subject_id: int
    import_task_id: Optional[int] = None
    original_filename: Optional[str] = None
    content: dict[str, Any]
    q_type: QuestionType
    options: list[PracticeOption] = Field(default_factory=list)
    answer: Optional[dict[str, Any]] = None
    analysis: Optional[dict[str, Any]] = None
    last_wrong_at: datetime
    wrong_count: int
