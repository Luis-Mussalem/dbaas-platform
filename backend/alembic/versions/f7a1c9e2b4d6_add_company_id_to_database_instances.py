"""add company_id to database_instances

Revision ID: f7a1c9e2b4d6
Revises: b2c4f6a8d0e1
Create Date: 2026-06-16 14:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a1c9e2b4d6'
down_revision: Union[str, None] = 'b2c4f6a8d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Coluna nullable + índice + FK (SET NULL), mesmo padrão de users.company_id.
    op.add_column(
        'database_instances',
        sa.Column('company_id', sa.UUID(), nullable=True),
    )
    op.create_index(
        op.f('ix_database_instances_company_id'),
        'database_instances',
        ['company_id'],
        unique=False,
    )
    op.create_foreign_key(
        'fk_database_instances_company_id_companies',
        'database_instances',
        'companies',
        ['company_id'],
        ['id'],
        ondelete='SET NULL',
    )

    # Backfill: atribui as instâncias órfãs à empresa de demonstração.
    # O EXISTS evita rodar o UPDATE em ambientes onde essa empresa não existe
    # (ex.: banco de teste/CI vazio) — ali o backfill simplesmente não se aplica.
    op.execute(
        """
        UPDATE database_instances
        SET company_id = (
            SELECT id FROM companies
            WHERE name = 'Empresa Demonstração'
            ORDER BY created_at
            LIMIT 1
        )
        WHERE company_id IS NULL
          AND EXISTS (
            SELECT 1 FROM companies WHERE name = 'Empresa Demonstração'
        )
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_database_instances_company_id_companies',
        'database_instances',
        type_='foreignkey',
    )
    op.drop_index(
        op.f('ix_database_instances_company_id'),
        table_name='database_instances',
    )
    op.drop_column('database_instances', 'company_id')
