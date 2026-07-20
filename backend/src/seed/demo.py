"""
Seed da frota de demonstração (multi-tenant) — para recrutadores explorarem o
produto já populado num clone limpo.

Cria, de forma idempotente:
- 3 empresas fictícias + 5 usuários cada (1 admin de empresa + 4 membros), todos
  com a mesma senha demo (dado mock, sem segredo real).
- 2 instâncias por empresa (prod + staging), com região e ambiente.

Modo de provisionamento:
- **Docker disponível** (docker compose num host Linux, ou uvicorn no host): cria
  CONTAINERS PostgreSQL REAIS e carrega ~100 linhas de dados fictícios na DB de
  produção. SQL Console, logs e métricas ao vivo funcionam de verdade.
- **Sem Docker** (ex.: Docker Desktop em Mac/Windows): cai para registros
  dados-apenas (STOPPED) com histórico de métricas sintético, para o dashboard
  ainda aparecer populado (mapa de regiões, cards, sparklines).

Executado automaticamente pelo docker compose após as migrations. Idempotente:
instâncias já existentes (por nome+empresa) são puladas, então religar o stack
não recria nada. Também roda à mão, a partir de backend/ com a venv ativa:

    python -m src.seed.demo            # semeia
    python -m src.seed.demo --clear    # remove a frota demo (containers + registros)
"""
import asyncio
import logging
import sys
from pathlib import Path

import psycopg

from src.core.database import SessionLocal
from src.core.encryption import decrypt_value
from src.models.audit_log import AuditLog
from src.models.backup import Backup, BackupSchedule
from src.models.company import Company
from src.models.database_instance import DatabaseInstance, Environment, InstanceStatus
from src.models.metric import Metric
from src.models.user import User, UserRole
from src.schemas.instance import InstanceCreate
from src.seed import history
from src.services.instance import create_instance

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent / "data"
DEMO_MARKER = "__demo_fleet__"  # marca as instâncias deste seed (idempotência/teardown)

# Senha única de demonstração. Atende à política (12+ chars, maiúscula, minúscula,
# dígito e símbolo). Dado mock — impresso no log para facilitar o login.
DEMO_PASSWORD = "DemoPass123!"

MEMBER_NAMES = ["ana", "bruno", "carla", "diego"]

# Configuração por empresa: região, admin, dataset (csv/tabela/DDL) e as 2
# instâncias (nome, ambiente, cpu, memória MB, storage GB). A ordem das colunas
# no DDL bate com o cabeçalho do CSV (necessário para o COPY).
COMPANIES: dict[str, dict] = {
    "Neptune Payments": {
        "slug": "neptune",
        "region": "sa-east-1",
        "csv": "neptune_transactions.csv",
        "table": "transactions",
        "ddl": """
            CREATE TABLE transactions (
                id              INTEGER PRIMARY KEY,
                transaction_ref TEXT UNIQUE NOT NULL,
                customer_name   TEXT NOT NULL,
                merchant        TEXT NOT NULL,
                amount          NUMERIC(12,2) NOT NULL,
                currency        CHAR(3) NOT NULL,
                method          TEXT NOT NULL,
                status          TEXT NOT NULL,
                fee             NUMERIC(8,2) NOT NULL,
                created_at      TIMESTAMP NOT NULL
            )
        """,
        "instances": [
            ("neptune-payments-prod", Environment.PRODUCTION, 2, 2048, 50),
            ("neptune-payments-staging", Environment.STAGING, 1, 1024, 20),
        ],
    },
    "Saturn Music Store": {
        "slug": "saturn",
        "region": "us-east-1",
        "csv": "saturn_products.csv",
        "table": "products",
        "ddl": """
            CREATE TABLE products (
                id             INTEGER PRIMARY KEY,
                sku            TEXT UNIQUE NOT NULL,
                name           TEXT NOT NULL,
                category       TEXT NOT NULL,
                brand          TEXT NOT NULL,
                price          NUMERIC(10,2) NOT NULL,
                stock_quantity INTEGER NOT NULL,
                rating         NUMERIC(2,1) NOT NULL,
                released_year  INTEGER NOT NULL
            )
        """,
        "instances": [
            ("saturn-store-prod", Environment.PRODUCTION, 2, 2048, 50),
            ("saturn-store-staging", Environment.STAGING, 1, 1024, 20),
        ],
    },
    "Jupiter Clothing": {
        "slug": "jupiter",
        "region": "eu-west-1",
        "csv": "jupiter_inventory.csv",
        "table": "inventory",
        "ddl": """
            CREATE TABLE inventory (
                id             INTEGER PRIMARY KEY,
                sku            TEXT UNIQUE NOT NULL,
                product_name   TEXT NOT NULL,
                category       TEXT NOT NULL,
                size           TEXT NOT NULL,
                color          TEXT NOT NULL,
                price          NUMERIC(8,2) NOT NULL,
                stock_quantity INTEGER NOT NULL,
                supplier       TEXT NOT NULL
            )
        """,
        "instances": [
            ("jupiter-clothing-prod", Environment.PRODUCTION, 2, 2048, 50),
            ("jupiter-clothing-staging", Environment.STAGING, 1, 1024, 20),
        ],
    },
}


# --------------------------------------------------------------------------- #
# Empresas e usuários
# --------------------------------------------------------------------------- #
def _get_or_create_company(db, name: str) -> Company:
    company = db.query(Company).filter(Company.name == name).first()
    if company is None:
        company = Company(name=name)
        db.add(company)
        db.commit()
        db.refresh(company)
    return company


def _get_or_create_user(db, email: str, company_id, role: UserRole) -> User:
    from src.core.security import hash_password

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(
            email=email,
            hashed_password=hash_password(DEMO_PASSWORD),
            is_superuser=False,
            is_active=True,
            role=role,
            company_id=company_id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _seed_company_and_users(db, company_name: str, slug: str) -> tuple[Company, User]:
    company = _get_or_create_company(db, company_name)
    admin_email = f"admin@{slug}.example"
    admin = _get_or_create_user(db, admin_email, company.id, UserRole.ADMIN)
    for name in MEMBER_NAMES:
        _get_or_create_user(db, f"{name}@{slug}.example", company.id, UserRole.MEMBER)
    return company, admin


# --------------------------------------------------------------------------- #
# Provisionamento real vs. fallback dados-apenas
# --------------------------------------------------------------------------- #
def _provisioner_available() -> bool:
    """True se o daemon Docker está acessível (senão, seed dados-apenas).

    get_provisioner() bate no daemon já na construção (via _ensure_network), então
    levanta docker.errors.DockerException se o Docker não estiver acessível.
    """
    try:
        from src.services.provisioning import get_provisioner

        get_provisioner()
        return True
    except Exception as exc:
        logger.info("Seed demo: Docker indisponível (%s) — usando modo dados-apenas.", exc)
        return False


def _existing_instance(db, name: str, company_id):
    return (
        db.query(DatabaseInstance)
        .filter(
            DatabaseInstance.name == name,
            DatabaseInstance.company_id == company_id,
            DatabaseInstance.deleted_at.is_(None),
        )
        .first()
    )


def _load_dataset(prod: DatabaseInstance, table: str, ddl: str, csv_name: str) -> int:
    """Cria a tabela e carrega o CSV via COPY na DB da instância de produção."""
    uri = decrypt_value(prod.connection_uri)
    csv_path = _DATA_DIR / csv_name
    with psycopg.connect(uri, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {table}")
            cur.execute(ddl)
            with csv_path.open("r", encoding="utf-8") as fh:
                with cur.copy(f"COPY {table} FROM STDIN WITH (FORMAT csv, HEADER true)") as copy:
                    copy.write(fh.read())
            count = cur.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    return count


def _seed_real(db, company: Company, admin: User, cfg: dict) -> None:
    """Provisiona containers reais e carrega o dataset na instância de produção."""
    prod = None
    for name, env, cpu, mem, storage in cfg["instances"]:
        inst = _existing_instance(db, name, company.id)
        if inst is None:
            data = InstanceCreate(
                name=name,
                engine_version="16",
                cpu=cpu,
                memory_mb=mem,
                storage_gb=storage,
                region=cfg["region"],
                environment=env,
                notes=DEMO_MARKER,
            )
            logger.info("Seed demo: provisionando %s ...", name)
            inst = asyncio.run(create_instance(db, data, admin))
            logger.info("Seed demo:   -> %s em %s:%s", inst.status.value, inst.host, inst.port)
        if env == Environment.PRODUCTION:
            prod = inst

    # Só carrega o dataset se acabamos de provisionar (evita recarregar em reruns).
    if prod is not None and prod.connection_uri:
        table = cfg["table"]
        with psycopg.connect(decrypt_value(prod.connection_uri)) as conn:
            exists = conn.execute(
                "SELECT to_regclass(%s) IS NOT NULL", (table,)
            ).fetchone()[0]
        if not exists:
            n = _load_dataset(prod, table, cfg["ddl"], cfg["csv"])
            logger.info("Seed demo: %s — %d linhas em '%s' (prod)", company.name, n, table)


def _seed_data_only(db, company: Company, cfg: dict) -> None:
    """Insere registros STOPPED (sem Docker). O histórico — métricas inclusas —
    é semeado depois por history.enrich_fleet(), igual ao caminho real."""
    for name, env, cpu, mem, storage in cfg["instances"]:
        if _existing_instance(db, name, company.id) is not None:
            continue
        inst = DatabaseInstance(
            name=name,
            engine_version="16",
            status=InstanceStatus.STOPPED,
            region=cfg["region"],
            environment=env,
            cpu=cpu,
            memory_mb=mem,
            storage_gb=storage,
            host="demo.invalid",
            port=5432,
            db_name=name.replace("-", "_"),
            db_user="app",
            connection_uri=None,  # demo — nada conecta de verdade
            notes=DEMO_MARKER,
            company_id=company.id,
        )
        db.add(inst)
        db.commit()
        db.refresh(inst)
        logger.info("Seed demo: %s (dados-apenas, %s, %s)", name, cfg["region"], env.value)


# --------------------------------------------------------------------------- #
# Orquestração
# --------------------------------------------------------------------------- #
def seed(db) -> None:
    can_provision = _provisioner_available()
    mode = "containers reais" if can_provision else "dados-apenas"
    logger.info("Seed demo: iniciando (%s).", mode)
    for company_name, cfg in COMPANIES.items():
        company, admin = _seed_company_and_users(db, company_name, cfg["slug"])
        if can_provision:
            _seed_real(db, company, admin, cfg)
        else:
            _seed_data_only(db, company, cfg)
    # Enriquece a frota com histórico (métricas, uptime, alertas, backups,
    # manutenção, audit) — idempotente, roda nos dois modos.
    history.enrich_fleet(db)
    logger.info("Seed demo: concluído. Login: qualquer usuário @{neptune,saturn,jupiter}.example / %s", DEMO_PASSWORD)


def clear(db) -> int:
    """Remove a frota demo (containers, se houver, + registros + métricas + empresas)."""
    removed = 0
    demos = db.query(DatabaseInstance).filter(DatabaseInstance.notes == DEMO_MARKER).all()
    if demos:
        try:
            from src.services.provisioning import get_provisioner

            provisioner = get_provisioner()
        except Exception:
            provisioner = None
        for inst in demos:
            if provisioner is not None and inst.connection_uri:
                try:
                    provisioner.delete(inst.id)
                except Exception as exc:
                    logger.warning("Seed demo: delete do container %s falhou: %s", inst.name, exc)
            db.query(Metric).filter(Metric.instance_id == inst.id).delete(synchronize_session=False)
            # Backups e schedules referenciam instance_id sem FK — não caem no
            # cascade do DELETE da instância (alertas, manutenção e status_history
            # caem, pois têm FK ON DELETE CASCADE). Removê-los à mão.
            db.query(Backup).filter(Backup.instance_id == inst.id).delete(synchronize_session=False)
            db.query(BackupSchedule).filter(BackupSchedule.instance_id == inst.id).delete(synchronize_session=False)
            db.delete(inst)
            removed += 1
        db.commit()
    for company_name, cfg in COMPANIES.items():
        company = db.query(Company).filter(Company.name == company_name).first()
        if company is None:
            continue
        # Audit logs têm FK SET NULL para company — apagá-los explicitamente
        # (senão sobrariam órfãos com company_id nulo após o delete da empresa).
        db.query(AuditLog).filter(AuditLog.company_id == company.id).delete(synchronize_session=False)
        db.query(User).filter(User.company_id == company.id).delete(synchronize_session=False)
        db.delete(company)
    db.commit()
    return removed


def run(clear_only: bool = False) -> None:
    db = SessionLocal()
    try:
        if clear_only:
            n = clear(db)
            logger.info("Seed demo: removidas %d instâncias e as 3 empresas demo.", n)
        else:
            seed(db)
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run(clear_only="--clear" in sys.argv)
