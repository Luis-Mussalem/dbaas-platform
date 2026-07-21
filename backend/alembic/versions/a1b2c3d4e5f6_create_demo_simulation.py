"""create demo_simulation

Revision ID: a1b2c3d4e5f6
Revises: e5a7c9b1d3f2
Create Date: 2026-07-20 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'e5a7c9b1d3f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tabela singleton: guarda o estado do roteiro de demonstração (uma linha).
    # create_type=False: o tipo é criado explicitamente logo abaixo. Sem isso o
    # create_table tentaria criá-lo de novo e o upgrade falharia com
    # DuplicateObject.
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


def downgrade() -> None:
    op.drop_table('demo_simulation')
    sa.Enum(name='simulationphase').drop(op.get_bind(), checkfirst=True)
