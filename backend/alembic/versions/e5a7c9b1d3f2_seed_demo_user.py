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


# Conta demo do portfólio (documentada no README). superuser de acesso completo —
# recrutadores exploram tudo, inclusive criar/parar/excluir instâncias. Roda só
# localmente, com dados de seed fictícios, então acesso total é intencional.
# Hash bcrypt pré-computado da senha "dev-test-2026" (literal para a migração não
# depender do código de hashing).
DEMO_EMAIL = "dev-test@local.dev"
DEMO_PASSWORD_HASH = "$2b$12$hVmRLO.9ZgHLWxfBRSmHxO1HzDmG4evKnNS9XQa86jxWZBo7jLdTy"


def upgrade() -> None:
    # Seed idempotente (ON CONFLICT no e-mail único): id via gen_random_uuid()
    # (PG16), created_at/updated_at pelo server_default now(); role precisa de
    # cast explícito para o enum userrole.
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
