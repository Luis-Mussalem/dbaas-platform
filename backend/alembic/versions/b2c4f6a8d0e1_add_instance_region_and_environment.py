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
    # Creates the 'environment' enum type before adding the column that uses it.
    # checkfirst=True makes the migration idempotent if the type already exists.
    #
    # The labels are the Python enum's NAMES (uppercase) — that's what SQLAlchemy
    # emits by default and the convention of the existing enums (instancestatus,
    # backupstatus...). Using the lowercase values here would break the INSERTs.
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
            # create_type=False: the type was already created above — avoids a duplicate CREATE TYPE.
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
