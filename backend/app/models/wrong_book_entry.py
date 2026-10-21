from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, func

from app.models.base import Base


class WrongBookEntry(Base):
    __tablename__ = "wrong_book_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "question_id", name="uq_wrong_book_user_question"),
        Index("ix_wrong_book_user_last_wrong", "user_id", "last_wrong_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(Integer, nullable=False)
    subject_id = Column(Integer, nullable=False)
    import_task_id = Column(Integer, nullable=True)
    original_filename = Column(String(255), nullable=True)
    question_snapshot = Column(JSON, nullable=False)
    wrong_count = Column(Integer, nullable=False, default=1, server_default="1")
    first_wrong_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=func.now())
    last_wrong_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=func.now())
