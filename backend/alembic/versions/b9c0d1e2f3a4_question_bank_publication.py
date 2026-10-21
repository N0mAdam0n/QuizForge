"""Track publication state for complete imported question banks.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "import_tasks",
        sa.Column(
            "publication_status",
            sa.String(length=16),
            server_default="published",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("import_tasks", "publication_status")
