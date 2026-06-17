"""add company_id to audit_logs

Revision ID: 1a2b3c4d5e6f
Revises: ebeb7b6edbf3
Create Date: 2026-06-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, None] = 'a7d3e2f5c1b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'audit_logs',
        sa.Column('company_id', sa.UUID(), nullable=True),
    )
    op.create_index(
        op.f('ix_audit_logs_company_id'),
        'audit_logs',
        ['company_id'],
        unique=False,
    )
    op.create_index(
        'ix_audit_logs_company_timestamp',
        'audit_logs',
        ['company_id', 'timestamp'],
        unique=False,
    )
    op.create_foreign_key(
        'fk_audit_logs_company_id_companies',
        'audit_logs',
        'companies',
        ['company_id'],
        ['id'],
        ondelete='SET NULL',
    )

    # Backfill a partir do ator: atribui às entradas existentes o company_id
    # do usuário que as gerou. Entradas de sistema (user_id NULL) ficam como NULL.
    op.execute(
        """
        UPDATE audit_logs
        SET company_id = (
            SELECT company_id FROM users WHERE users.id = audit_logs.user_id
        )
        WHERE user_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_audit_logs_company_id_companies',
        'audit_logs',
        type_='foreignkey',
    )
    op.drop_index(
        'ix_audit_logs_company_timestamp',
        table_name='audit_logs',
    )
    op.drop_index(
        op.f('ix_audit_logs_company_id'),
        table_name='audit_logs',
    )
    op.drop_column('audit_logs', 'company_id')
