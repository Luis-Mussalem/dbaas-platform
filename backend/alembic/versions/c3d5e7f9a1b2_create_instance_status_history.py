"""create_instance_status_history

Revision ID: c3d5e7f9a1b2
Revises: 1a2b3c4d5e6f
Create Date: 2026-07-02 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3d5e7f9a1b2'
down_revision: Union[str, None] = '1a2b3c4d5e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'instance_status_history',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('instance_id', sa.UUID(), nullable=False),
        # Reuses the enum type already created by database_instances.
        # postgresql.ENUM(create_type=False) references the type without reissuing
        # the CREATE TYPE (the generic sa.Enum's create_type=False is ignored).
        sa.Column(
            'status',
            postgresql.ENUM(
                'PENDING', 'PROVISIONING', 'RUNNING', 'STOPPED',
                'DELETING', 'DELETED', 'FAILED',
                name='instancestatus',
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            'changed_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['instance_id'], ['database_instances.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_instance_status_history_instance_id'),
        'instance_status_history',
        ['instance_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_instance_status_history_changed_at'),
        'instance_status_history',
        ['changed_at'],
        unique=False,
    )
    op.create_index(
        'ix_instance_status_history_instance_changed',
        'instance_status_history',
        ['instance_id', 'changed_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        'ix_instance_status_history_instance_changed',
        table_name='instance_status_history',
    )
    op.drop_index(
        op.f('ix_instance_status_history_changed_at'),
        table_name='instance_status_history',
    )
    op.drop_index(
        op.f('ix_instance_status_history_instance_id'),
        table_name='instance_status_history',
    )
    op.drop_table('instance_status_history')
