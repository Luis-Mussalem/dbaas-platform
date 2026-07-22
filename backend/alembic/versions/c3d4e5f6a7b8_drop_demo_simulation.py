"""drop demo_simulation

The scripted "Simulate usage" reel was removed: the demo fleet is now populated
on boot and kept alive by a continuous baseline load, with no on-demand director
to persist state for. This drops the singleton table and its enum.

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-07-22 22:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('demo_simulation')
    sa.Enum(name='simulationphase').drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    simulation_phase = postgresql.ENUM(
        'IDLE', 'BACKFILL', 'WARMUP', 'ALERT', 'BACKUP', 'MAINTENANCE',
        'RECOVER', 'STEADY',
        name='simulationphase',
        create_type=False,
    )
    simulation_phase.create(op.get_bind(), checkfirst=True)
    op.create_table(
        'demo_simulation',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('phase', simulation_phase, nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('phase_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('stopped_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('has_simulated_data', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('speed_factor', sa.Float(), nullable=False, server_default='1'),
        sa.Column('restore_points', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default='{}'),
        sa.Column('events', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default='[]'),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
