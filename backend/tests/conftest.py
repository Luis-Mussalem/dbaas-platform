"""
Shared test configuration (pytest).

New concepts here:
- conftest.py: pytest loads this file automatically. Anything defined
  as a fixture becomes available to every test with no explicit import.
- fixture: a function that prepares a resource (database, HTTP client, user) and
  hands it to the test. It's the testing equivalent of FastAPI's Depends().
- Isolated test database: we use a separate PostgreSQL database (dbaas_test) to
  never touch development data.

Why set the environment variables BEFORE importing src.*?
src.core.config.Settings() is instantiated at import time, and
src.core.database creates the engine/SessionLocal tied to that configuration.
Setting the envs here at the top — before any import from src — makes the
entire application (including AuditMiddleware, which opens its own SessionLocal)
point to the test database automatically. No monkeypatch needed.
"""
import os
import uuid

from cryptography.fernet import Fernet

# --- Test environment: SET BEFORE any import from src.* ---
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
from src.main import app  # noqa: E402  (imports app → registers all models on the metadata)
from src.models.company import Company  # noqa: E402
from src.models.user import User, UserRole  # noqa: E402

# Strong password reused across tests (meets the policy: 12+ chars, uppercase,
# lowercase, digit, and symbol). Centralized to avoid repeating literals.
TEST_PASSWORD = "ValidPass123!"

# Turns off rate limiting in tests. Without this, repeated logins/registrations across
# tests would hit the limits (5/min, 3/min) and produce false 429s.
limiter.enabled = False


def _ensure_test_database() -> None:
    """
    Creates the dbaas_test database if it doesn't already exist.

    CREATE DATABASE doesn't run inside a transaction, so we connect to the
    'postgres' maintenance database with autocommit. The credentials (user/password/
    host/port) come from .env — only the database name was overridden to dbaas_test.
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
                # Name controlled by us (a constant), no injection risk here.
                cur.execute(f'CREATE DATABASE "{settings.POSTGRES_DB}"')
    finally:
        admin_conn.close()


@pytest.fixture(scope="session", autouse=True)
def _setup_database():
    """
    Creates the database and schema once per test session.

    We use Base.metadata.create_all (not Alembic): the test schema mirrors the
    models. Fast and sufficient for behavior tests. The migrations
    are still validated when running the real application.
    """
    _ensure_test_database()
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    """
    Clears all tables AFTER each test, guaranteeing independence.

    TRUNCATE ... RESTART IDENTITY CASCADE zeroes out the tables and respects the FKs.
    Runs on its own connection (engine.begin), picking up even what the app
    committed via SessionLocal during the request.
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
    """Direct SQLAlchemy session — for setting up test data (arrange)."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> TestClient:
    """
    Test HTTP client.

    Instantiated WITHOUT 'with': the lifespan doesn't run, so there's no connection to
    Docker nor initialization of the background pollers. Ideal for testing routes.
    """
    return TestClient(app)


@pytest.fixture
def make_user(db):
    """
    Factory for users persisted to the test database.

    Returns a function for the test to create as many users as needed, with
    customizable email/role. Commits so the request (which uses a different
    session, but the same database) can see the user.
    """
    created = []

    def _make(
        email: str = "user@example.com",
        password: str = TEST_PASSWORD,
        is_superuser: bool = False,
        is_active: bool = True,
        company_id: uuid.UUID | None = None,
        role: UserRole = UserRole.MEMBER,
    ) -> User:
        user = User(
            email=email,
            hashed_password=hash_password(password),
            is_superuser=is_superuser,
            is_active=is_active,
            company_id=company_id,
            role=role,
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
    Creates a user and returns (headers, user) with a valid access token.

    The token is generated directly via create_access_token — decouples route
    tests from the login flow (which has its own tests in test_auth.py).
    """
    def _build(
        email: str = "user@example.com",
        is_superuser: bool = False,
        company_id: uuid.UUID | None = None,
        role: UserRole = UserRole.MEMBER,
    ) -> tuple[dict, User]:
        user = make_user(
            email=email, is_superuser=is_superuser, company_id=company_id, role=role
        )
        token = create_access_token({"sub": str(user.id)})
        return {"Authorization": f"Bearer {token}"}, user

    return _build


@pytest.fixture
def make_company(db):
    """Factory for companies persisted to the test database (multi-tenant)."""
    def _make(name: str = "Acme Inc") -> Company:
        company = Company(name=name)
        db.add(company)
        db.commit()
        db.refresh(company)
        return company

    return _make
