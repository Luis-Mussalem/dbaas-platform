"""add role to users

Revision ID: a7d3e2f5c1b9
Revises: f7a1c9e2b4d6
Create Date: 2026-06-17 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d3e2f5c1b9'
down_revision: Union[str, None] = 'f7a1c9e2b4d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the enum type with lowercase values (admin, member)
    userrole = sa.Enum("admin", "member", name="userrole")
    userrole.create(op.get_bind(), checkfirst=True)

    # Add the column with server_default to backfill existing rows to "member"
    op.add_column(
        'users',
        sa.Column('role', userrole, nullable=False, server_default="member")
    )


def downgrade() -> None:
    op.drop_column('users', 'role')
    sa.Enum(name="userrole").drop(op.get_bind(), checkfirst=True)
