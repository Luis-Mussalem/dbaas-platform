"""
Configuração compartilhada dos testes (pytest).

Conceitos novos aqui:
- conftest.py: o pytest carrega este arquivo automaticamente. Tudo definido
  como fixture fica disponível para todos os testes sem import explícito.
- fixture: função que prepara um recurso (banco, cliente HTTP, usuário) e o
  entrega ao teste. É o equivalente em testes ao Depends() do FastAPI.
- Banco de teste isolado: usamos um banco PostgreSQL separado (dbaas_test) para
  nunca tocar nos dados de desenvolvimento.

Por que definir as variáveis de ambiente ANTES de importar src.*?
src.core.config.Settings() é instanciado no momento do import, e
src.core.database cria o engine/SessionLocal ligados a essa configuração.
Definindo as envs aqui no topo — antes de qualquer import de src — toda a
aplicação (inclusive o AuditMiddleware, que abre seu próprio SessionLocal)
passa a apontar para o banco de teste automaticamente. Sem monkeypatch.
"""
import os

from cryptography.fernet import Fernet

# --- Ambiente de teste: DEFINIDO ANTES de qualquer import de src.* ---
os.environ["POSTGRES_DB"] = "dbaas_test"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-do-not-use-in-production"
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()
os.environ["PROVISIONER_SUPERUSER_PASSWORD"] = "test-provisioner-password"
os.environ["REGISTRATION_ENABLED"] = "false"

import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.core.config import settings  # noqa: E402
from src.core.database import Base, SessionLocal, engine  # noqa: E402
from src.core.rate_limit import limiter  # noqa: E402
from src.core.security import create_access_token, hash_password  # noqa: E402
from src.main import app  # noqa: E402  (importa app → registra todos os models no metadata)
from src.models.user import User  # noqa: E402

# Senha forte reutilizada nos testes (atende à política: 12+ chars, maiúscula,
# minúscula, dígito e símbolo). Centralizada para não repetir literais.
TEST_PASSWORD = "ValidPass123!"

# Desliga o rate limiting nos testes. Sem isto, logins/registros repetidos entre
# testes estourariam os limites (5/min, 3/min) e gerariam 429 falsos.
limiter.enabled = False


def _ensure_test_database() -> None:
    """
    Cria o banco dbaas_test se ainda não existir.

    CREATE DATABASE não roda dentro de uma transação, por isso conectamos ao
    banco de manutenção 'postgres' com autocommit. As credenciais (user/senha/
    host/porta) vêm do .env — só o nome do banco foi sobrescrito para dbaas_test.
    """
    admin_conn = psycopg.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname="postgres",
        autocommit=True,
    )
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (settings.POSTGRES_DB,),
            )
            if cur.fetchone() is None:
                # Nome controlado por nós (constante), não há injeção aqui.
                cur.execute(f'CREATE DATABASE "{settings.POSTGRES_DB}"')
    finally:
        admin_conn.close()


@pytest.fixture(scope="session", autouse=True)
def _setup_database():
    """
    Cria o banco e o schema uma vez por sessão de teste.

    Usamos Base.metadata.create_all (não Alembic): o schema de teste espelha os
    models. Rápido e suficiente para testes de comportamento. As migrações
    continuam sendo validadas ao rodar a aplicação de verdade.
    """
    _ensure_test_database()
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    """
    Limpa todas as tabelas DEPOIS de cada teste, garantindo independência.

    TRUNCATE ... RESTART IDENTITY CASCADE zera as tabelas e respeita as FKs.
    Roda em conexão própria (engine.begin), pegando inclusive o que o app
    commitou via SessionLocal durante o request.
    """
    yield
    tables = ", ".join(
        f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables)
    )
    if tables:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")


@pytest.fixture
def db() -> Session:
    """Sessão SQLAlchemy direta — para montar dados de teste (arrange)."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> TestClient:
    """
    Cliente HTTP de teste.

    Instanciado SEM 'with': o lifespan não roda, então não há conexão com o
    Docker nem inicialização dos pollers de background. Ideal para testar rotas.
    """
    return TestClient(app)


@pytest.fixture
def make_user(db):
    """
    Fábrica de usuários persistidos no banco de teste.

    Retorna uma função para o teste criar quantos usuários precisar, com
    e-mail/papel customizáveis. Commita para que o request (que usa outra
    sessão, mas o mesmo banco) enxergue o usuário.
    """
    created = []

    def _make(
        email: str = "user@example.com",
        password: str = TEST_PASSWORD,
        is_superuser: bool = False,
        is_active: bool = True,
    ) -> User:
        user = User(
            email=email,
            hashed_password=hash_password(password),
            is_superuser=is_superuser,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        created.append(user)
        return user

    return _make


@pytest.fixture
def auth_headers(make_user):
    """
    Cria um usuário e devolve (headers, user) com um access token válido.

    O token é gerado direto via create_access_token — desacopla os testes de
    rotas do fluxo de login (que tem testes próprios em test_auth.py).
    """
    def _build(
        email: str = "user@example.com",
        is_superuser: bool = False,
    ) -> tuple[dict, User]:
        user = make_user(email=email, is_superuser=is_superuser)
        token = create_access_token({"sub": str(user.id)})
        return {"Authorization": f"Bearer {token}"}, user

    return _build
