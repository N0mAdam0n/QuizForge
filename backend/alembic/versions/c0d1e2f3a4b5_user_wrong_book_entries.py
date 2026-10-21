"""Persist user-scoped wrong-book snapshots across question-bank changes.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wrong_book_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("import_task_id", sa.Integer(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("question_snapshot", sa.JSON(), nullable=False),
        sa.Column("wrong_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "first_wrong_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_wrong_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "question_id", name="uq_wrong_book_user_question"),
    )
    op.create_index(
        "ix_wrong_book_user_last_wrong",
        "wrong_book_entries",
        ["user_id", "last_wrong_at"],
    )
    _backfill_wrong_book_entries()


def _decode_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Cannot migrate malformed question JSON") from exc
    return value


def _backfill_wrong_book_entries() -> None:
    bind = op.get_bind()
    attempts = sa.table(
        "practice_attempts",
        sa.column("user_id", sa.Integer()),
        sa.column("question_id", sa.Integer()),
        sa.column("is_correct", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
    )
    question = sa.table(
        "questions",
        sa.column("id", sa.Integer()),
        sa.column("subject_id", sa.Integer()),
        sa.column("import_task_id", sa.Integer()),
        sa.column("content", sa.Text()),
        sa.column("q_type", sa.String()),
        sa.column("options", sa.JSON()),
        sa.column("answer", sa.Text()),
        sa.column("analysis", sa.Text()),
    )
    import_task = sa.table(
        "import_tasks",
        sa.column("id", sa.Integer()),
        sa.column("original_filename", sa.String()),
    )
    attempt_groups = bind.execute(
        sa.select(
            attempts.c.user_id,
            attempts.c.question_id,
            sa.func.count().label("wrong_count"),
            sa.func.min(attempts.c.created_at).label("first_wrong_at"),
            sa.func.max(attempts.c.created_at).label("last_wrong_at"),
        )
        .where(attempts.c.is_correct.is_(False))
        .group_by(attempts.c.user_id, attempts.c.question_id)
    ).mappings().all()
    if not attempt_groups:
        return

    question_ids = list({row["question_id"] for row in attempt_groups})
    questions = {}
    for start in range(0, len(question_ids), 500):
        batch_ids = question_ids[start : start + 500]
        rows = bind.execute(
            sa.select(
                question.c.id,
                question.c.subject_id,
                question.c.import_task_id,
                question.c.content,
                question.c.q_type,
                question.c.options,
                question.c.answer,
                question.c.analysis,
                import_task.c.original_filename,
            )
            .select_from(
                question.outerjoin(import_task, import_task.c.id == question.c.import_task_id)
            )
            .where(question.c.id.in_(batch_ids))
        ).mappings()
        questions.update({row["id"]: row for row in rows})

    entries = []
    for attempt in attempt_groups:
        question_row = questions.get(attempt["question_id"])
        if question_row is None:
            continue
        content = _decode_json(question_row["content"])
        answer = _decode_json(question_row["answer"])
        if not isinstance(content, dict) or not isinstance(answer, dict):
            raise ValueError(
                f"Cannot migrate wrong answer for malformed question {attempt['question_id']}"
            )
        analysis = _decode_json(question_row["analysis"])
        entries.append(
            {
                "user_id": attempt["user_id"],
                "question_id": attempt["question_id"],
                "subject_id": question_row["subject_id"],
                "import_task_id": question_row["import_task_id"],
                "original_filename": question_row["original_filename"],
                "question_snapshot": {
                    "content": content,
                    "q_type": question_row["q_type"],
                    "options": question_row["options"] or [],
                    "answer": answer,
                    "analysis": analysis if isinstance(analysis, dict) else None,
                },
                "wrong_count": attempt["wrong_count"],
                "first_wrong_at": attempt["first_wrong_at"],
                "last_wrong_at": attempt["last_wrong_at"],
            }
        )
    if entries:
        op.bulk_insert(
            sa.table(
                "wrong_book_entries",
                sa.column("user_id", sa.Integer()),
                sa.column("question_id", sa.Integer()),
                sa.column("subject_id", sa.Integer()),
                sa.column("import_task_id", sa.Integer()),
                sa.column("original_filename", sa.String(length=255)),
                sa.column("question_snapshot", sa.JSON()),
                sa.column("wrong_count", sa.Integer()),
                sa.column("first_wrong_at", sa.DateTime()),
                sa.column("last_wrong_at", sa.DateTime()),
            ),
            entries,
        )


def downgrade() -> None:
    op.drop_index("ix_wrong_book_user_last_wrong", table_name="wrong_book_entries")
    op.drop_table("wrong_book_entries")
