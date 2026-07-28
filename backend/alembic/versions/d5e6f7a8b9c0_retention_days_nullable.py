"""make backup_schedules.retention_days nullable (NULL = keep indefinitely)

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-07-28 12:00:00.000000

The retention pipeline already understood "no expiry" end to end: the backup
service stamps ``expires_at`` only when a retention is given, and ``apply_retention``
never touches a row whose ``expires_at`` is NULL. The only thing missing was a way
to SAY it — the column was NOT NULL, so a schedule that had ever been given a
retention could not be moved back to "keep these forever" without deleting and
recreating it.

Nothing changes for existing rows: they all carry a value already, and the column
default (7 days) still applies to schedules created without one.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'backup_schedules',
        'retention_days',
        existing_type=sa.Integer(),
        nullable=True,
        comment='How many days to keep backups created by this schedule; NULL = keep indefinitely',
        existing_comment='How many days to keep backups created by this schedule',
    )


def downgrade() -> None:
    # Rows that opted into "keep forever" have no non-null value to go back to;
    # give them the original default so the NOT NULL can be restored.
    op.execute(
        sa.text("UPDATE backup_schedules SET retention_days = 7 WHERE retention_days IS NULL")
    )
    op.alter_column(
        'backup_schedules',
        'retention_days',
        existing_type=sa.Integer(),
        nullable=False,
        comment='How many days to keep backups created by this schedule',
        existing_comment='How many days to keep backups created by this schedule; NULL = keep indefinitely',
    )
