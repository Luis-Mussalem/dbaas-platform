"""create_replicas

Revision ID: d4f6a8b0c2e1
Revises: c3d5e7f9a1b2
Create Date: 2026-07-07 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4f6a8b0c2e1'
down_revision: Union[str, None] = 'c3d5e7f9a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'replicas',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('primary_instance_id', sa.UUID(), nullable=False),
        sa.Column('replica_instance_id', sa.UUID(), nullable=False),
        # Enum novo, criado inline (labels = nomes dos membros, maiúsculos —
        # padrão da casa; sem values_callable, como Backup/InstanceStatus).
        sa.Column(
            'replication_state',
            sa.Enum(
                'PENDING', 'PROVISIONING', 'STREAMING', 'CATCHUP',
                'DISCONNECTED', 'PROMOTED', 'FAILED',
                name='replicationstate',
            ),
            nullable=False,
        ),
        sa.Column('lag_bytes', sa.BigInteger(), nullable=True),
        sa.Column('lag_seconds', sa.Numeric(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_replicas_primary_instance_id'),
        'replicas',
        ['primary_instance_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_replicas_replica_instance_id'),
        'replicas',
        ['replica_instance_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_replicas_replication_state'),
        'replicas',
        ['replication_state'],
        unique=False,
    )
    op.create_index(
        'ix_replicas_primary_state',
        'replicas',
        ['primary_instance_id', 'replication_state'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_replicas_primary_state', table_name='replicas')
    op.drop_index(op.f('ix_replicas_replication_state'), table_name='replicas')
    op.drop_index(op.f('ix_replicas_replica_instance_id'), table_name='replicas')
    op.drop_index(op.f('ix_replicas_primary_instance_id'), table_name='replicas')
    op.drop_table('replicas')
    # Enum é dropado explicitamente: op.drop_table não remove o tipo no Postgres.
    sa.Enum(name='replicationstate').drop(op.get_bind(), checkfirst=True)
