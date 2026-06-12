"""add instance region and environment

Revision ID: b2c4f6a8d0e1
Revises: 6e199bf83633
Create Date: 2026-06-11 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b2c4f6a8d0e1'
down_revision: Union[str, None] = '6e199bf83633'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cria o tipo enum 'environment' antes de adicionar a coluna que o usa.
    # checkfirst=True torna a migration idempotente caso o tipo já exista.
    #
    # Os rótulos são os NOMES do enum Python (maiúsculos) — é o que o SQLAlchemy
    # emite por padrão e a convenção dos enums existentes (instancestatus,
    # backupstatus...). Usar os values minúsculos aqui quebraria os INSERTs.
    env = postgresql.ENUM(
        'PRODUCTION', 'STAGING', 'DEVELOPMENT', name='environment'
    )
    env.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'database_instances',
        sa.Column(
            'region',
            sa.String(length=64),
            nullable=True,
            comment='Region code, e.g. sa-east-1 / us-east-1 / eu-west-1',
        ),
    )
    op.add_column(
        'database_instances',
        sa.Column(
            'environment',
            # create_type=False: o tipo já foi criado acima — evita CREATE TYPE duplicado.
            postgresql.ENUM(
                'PRODUCTION', 'STAGING', 'DEVELOPMENT',
                name='environment', create_type=False,
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('database_instances', 'environment')
    op.drop_column('database_instances', 'region')
    postgresql.ENUM(name='environment').drop(op.get_bind(), checkfirst=True)
