"""seed the demo (portfolio) superuser

Revision ID: e5a7c9b1d3f2
Revises: d4f6a8b0c2e1
Create Date: 2026-07-16 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a7c9b1d3f2'
down_revision: Union[str, None] = 'd4f6a8b0c2e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Portfolio demo account (documented in the README). Full-access superuser —
# recruiters can explore everything, including creating/stopping/deleting instances.
# Runs only locally, with fictitious seed data, so full access is intentional.
# Pre-computed bcrypt hash of the password "dev-test-2026" (literal so the migration
# doesn't depend on the hashing code).
DEMO_EMAIL = "dev-test@local.dev"
DEMO_PASSWORD_HASH = "$2b$12$hVmRLO.9ZgHLWxfBRSmHxO1HzDmG4evKnNS9XQa86jxWZBo7jLdTy"


def upgrade() -> None:
    # Idempotent seed (ON CONFLICT on the unique email): id via gen_random_uuid()
    # (PG16), created_at/updated_at via server_default now(); role needs an
    # explicit cast to the userrole enum.
    op.execute(
        sa.text(
            """
            INSERT INTO users
                (id, email, hashed_password, is_active, is_superuser, role)
            VALUES
                (gen_random_uuid(), :email, :pwd, true, true, CAST(:role AS userrole))
            ON CONFLICT (email) DO NOTHING
            """
        ).bindparams(email=DEMO_EMAIL, pwd=DEMO_PASSWORD_HASH, role="admin")
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM users WHERE email = :email").bindparams(email=DEMO_EMAIL))
