"""Track question-bank scope on import batches.

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "import_tasks",
        sa.Column(
            "scope_type",
            sa.String(length=16),
            server_default="shared",
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE import_tasks
            SET scope_type = CASE
                WHEN EXISTS (
                    SELECT 1 FROM compositions c
                    WHERE c.source_import_task_id = import_tasks.id
                      AND c.scope_type = 'personal'
                ) THEN 'personal'
                WHEN EXISTS (
                    SELECT 1 FROM questions q
                    WHERE q.import_task_id = import_tasks.id
                      AND q.visibility = 'private'
                ) THEN 'personal'
                ELSE 'shared'
            END
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE import_tasks
            SET user_id = COALESCE(
                user_id,
                (
                    SELECT c.owner_id FROM compositions c
                    WHERE c.source_import_task_id = import_tasks.id
                      AND c.scope_type = 'personal'
                    LIMIT 1
                ),
                (
                    SELECT q.created_by FROM questions q
                    WHERE q.import_task_id = import_tasks.id
                      AND q.visibility = 'private'
                      AND q.created_by IS NOT NULL
                    ORDER BY q.id
                    LIMIT 1
                )
            )
            WHERE scope_type = 'personal'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE questions
            SET visibility = CASE
                WHEN (
                    SELECT t.scope_type FROM import_tasks t
                    WHERE t.id = questions.import_task_id
                ) = 'personal' AND visibility != 'group' THEN 'private'
                WHEN visibility = 'group' THEN 'group'
                ELSE 'public'
            END
            WHERE import_task_id IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_column("import_tasks", "scope_type")
