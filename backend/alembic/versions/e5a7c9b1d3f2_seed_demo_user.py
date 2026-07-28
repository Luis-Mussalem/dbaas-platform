"""seed the demo (portfolio) superuser — only when DEMO_MODE is on

Revision ID: e5a7c9b1d3f2
Revises: d4f6a8b0c2e1
Create Date: 2026-07-16 19:00:00.000000

"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a7c9b1d3f2'
down_revision: Union[str, None] = 'd4f6a8b0c2e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Portfolio demo account, documented in the README with its password in plain
# sight so a recruiter can log in and explore everything.
#
# GATED ON DEMO_MODE, and this is the important part. A migration runs on every
# deployment, including a real one — an unconditional INSERT here would create a
# full-access superuser, with a PUBLISHED password, in every database this schema
# is ever applied to, and no configuration could switch it off. `DEMO_MODE=false`
# skips it entirely; the first account is then created through the bootstrap path
# in services.auth.register_user, which promotes the first registration on an
# empty platform to superuser and locks the endpoint afterwards.
#
# Pre-computed bcrypt hash of the password "dev-test-2026" (a literal, so the
# migration doesn't depend on the application's hashing code).
DEMO_EMAIL = "dev-test@local.dev"
DEMO_PASSWORD_HASH = "$2b$12$hVmRLO.9ZgHLWxfBRSmHxO1HzDmG4evKnNS9XQa86jxWZBo7jLdTy"


def _demo_mode_enabled() -> bool:
    """
    Reads DEMO_MODE from the environment, defaulting to ON.

    Read from os.environ rather than from src.core.config on purpose: a migration
    must be runnable against a database without importing the application (and
    without tripping its startup validators). The default matches the app's own
    (DEMO_MODE=True), so an existing local checkout behaves exactly as before.
    """
    return os.getenv("DEMO_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}


def upgrade() -> None:
    if not _demo_mode_enabled():
        return

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
