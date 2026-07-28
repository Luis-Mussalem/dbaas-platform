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
from src.services.provisioning.types import ProvisionResult  # noqa: E402

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


# Sentinel telling auth_headers "the test didn't care which company" apart from
# "the test explicitly wants a company-less account". They are different scenarios:
# the platform scopes a regular user with no company to NOTHING (see
# core.scoping.CompanyScope), so a company-less default would make almost every
# route test 404 for reasons unrelated to what it is checking.
_UNSET = object()


@pytest.fixture
def default_company(make_company):
    """
    The shared tenant ordinary fixtures belong to. CALL IT to get the Company.

    Most route tests aren't about multi-tenancy — they need *a* tenant so the
    scoping rule is satisfied, and they don't care which. This is that tenant:
    `auth_headers()` puts its user in it, and the per-module instance fixtures file
    their instance under it, so the two line up by default. Tests that ARE about
    scoping (test_company_scoping.py, test_rbac.py) build their own companies and
    pass company_id explicitly.

    It is a FACTORY rather than a plain value so that merely depending on it costs
    nothing: a superuser test, or one that counts the rows in `companies`, would
    otherwise find a phantom company it never created. The company is built on the
    first call and cached, so every caller within one test shares the same row.
    """
    cache: dict[str, Company] = {}

    def _get() -> Company:
        if "company" not in cache:
            cache["company"] = make_company(name="Default Test Co")
        return cache["company"]

    return _get


@pytest.fixture
def auth_headers(make_user, default_company):
    """
    Creates a user and returns (headers, user) with a valid access token.

    The token is generated directly via create_access_token — decouples route
    tests from the login flow (which has its own tests in test_auth.py).

    A regular user lands in `default_company`; a superuser is created with no
    company, which is what the real platform superuser looks like. Pass
    `company_id=` explicitly to override either default (including `None`, for the
    company-less account the scoping rules deliberately show nothing to).

    The default ROLE is `admin`, because the default test actor is "an operator of
    this company" and the platform's write gate is admin-only (members observe,
    admins operate — see core.dependencies.get_current_company_admin). Tests about
    the member/admin boundary pass `role=UserRole.MEMBER` explicitly, which is what
    test_rbac.py and test_write_permissions.py do throughout.
    """
    def _build(
        email: str = "user@example.com",
        is_superuser: bool = False,
        company_id: uuid.UUID | None = _UNSET,
        role: UserRole = UserRole.ADMIN,
    ) -> tuple[dict, User]:
        if company_id is _UNSET:
            company_id = None if is_superuser else default_company().id
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


class FakeProvisioner:
    """
    Provisioner stub: records calls, doesn't touch Docker.

    Shared here because "create an instance through the API" is a prerequisite in
    several modules (lifecycle, scoping, RBAC), not just the instance tests.
    """

    def __init__(self) -> None:
        self.fail_create = False
        self.created: list[uuid.UUID] = []
        self.started: list[uuid.UUID] = []
        self.stopped: list[uuid.UUID] = []
        self.deleted: list[uuid.UUID] = []

    def create(self, instance_id, engine_version, memory_mb=None, cpu=None):
        if self.fail_create:
            # Message with an internal "secret" — the tests guarantee it does NOT leak.
            raise RuntimeError("docker daemon error at internal-host:5432")
        self.created.append(instance_id)
        return ProvisionResult(
            container_id="fake-container-id",
            host="127.0.0.1",
            port=55432,
            db_name="db_fakeinstance",
            db_user="inst_fakeinstance",
            db_password="fake-plaintext-password",
            container_name="dbaas-inst-fake",
        )

    def start(self, instance_id):
        self.started.append(instance_id)
        return 55433  # new port after restart (Docker republishes dynamically)

    def stop(self, instance_id):
        self.stopped.append(instance_id)

    def delete(self, instance_id):
        self.deleted.append(instance_id)

    def create_replica(
        self, replica_id, primary_id, engine_version,
        db_name, db_user, db_password, memory_mb=None, cpu=None,
    ):
        self.created.append(replica_id)
        return ProvisionResult(
            container_id="fake-replica-id",
            host="127.0.0.1",
            port=55434,
            db_name=db_name,
            db_user=db_user,
            db_password=db_password,
            container_name="dbaas-inst-fake-replica",
        )

    def promote_replica(self, instance_id):
        self.promoted.append(instance_id)

    def get_port(self, instance_id):
        return 55432

    def logs(self, instance_id, tail=200):
        return "fake logs"


# Every module that calls the provisioner imported the name into its own namespace
# (`from src.services.provisioning import get_provisioner`), so patching the factory
# alone would miss them. All the sites are listed here on purpose: a test that
# reaches an unpatched one talks to the REAL Docker daemon and leaves a live
# PostgreSQL container behind on the developer's machine — which is exactly what
# happened while writing test_write_permissions.py, and is invisible until you
# count containers.
_PROVISIONER_SITES = (
    "src.services.provisioning.factory.get_provisioner",
    "src.services.instance.get_provisioner",
    "src.services.replica.get_provisioner",
)


@pytest.fixture
def fake_provisioner(monkeypatch):
    """
    Replaces the provisioner everywhere it is looked up, with a stub.

    REQUIRED by any test that exercises a route which provisions, starts, stops,
    deletes or replicates — including tests that only care about the status code.
    Without it the request reaches Docker for real.
    """
    fake = FakeProvisioner()
    fake.promoted = []
    for site in _PROVISIONER_SITES:
        monkeypatch.setattr(site, lambda: fake)
    return fake
