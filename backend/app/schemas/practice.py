from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.models.question import QuestionType


PracticeMode = Literal["sequential", "random", "type", "wrong"]


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


class PracticeQuestionSet(BaseModel):
    mode: PracticeMode
    questions: list[PracticeQuestion]
    has_more: bool = False
    next_offset: int = 0


class PracticeAnswerSubmit(BaseModel):
    question_id: int
    subject_id: int
    mode: PracticeMode
    answer: Any = None
    self_assessed: Optional[bool] = None


class PracticeAnswerResult(BaseModel):
    question_id: int
    is_correct: Optional[bool]
    score: Optional[float]
    requires_self_assessment: bool = False
    correct_answer: Optional[dict[str, Any]] = None
    analysis: Optional[dict[str, Any]] = None
