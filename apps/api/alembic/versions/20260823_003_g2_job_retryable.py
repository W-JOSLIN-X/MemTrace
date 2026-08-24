"""Persist the G2 memory-job retryability decision.

Revision ID: 003_g2_job_retryable
Revises: 002_g2_memory_admission
Create Date: 2026-08-23 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003_g2_job_retryable"
down_revision: str | None = "002_g2_memory_admission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memory_jobs",
        sa.Column(
            "retryable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("memory_jobs") as batch_op:
        batch_op.drop_column("retryable")
