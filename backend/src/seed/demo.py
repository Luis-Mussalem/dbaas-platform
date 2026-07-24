"""
Seed da frota de demonstração (multi-tenant) — a frota que um clone limpo
entrega pronta para explorar.

O que este seed cria é REAL: empresas, usuários e containers PostgreSQL de
verdade com dados carregados. Além disso, no fim do boot ele deixa a frota VIVA:
semeia o histórico sintético (24h de métricas, uptime, backups, alertas,
manutenção, audit — via `seed/history.enrich_fleet`) e o gerador de carga
(`services/workload_simulator.py`) mantém uma carga-base contínua, para o
dashboard mostrar uma plataforma robusta e viva já no primeiro login, sem
ninguém precisar clicar em nada.

Cria, de forma idempotente:
- 3 empresas fictícias + 5 usuários cada (1 admin de empresa + 4 membros), todos
  com a mesma senha demo (dado mock, sem segredo real).
- 2 instâncias por empresa (prod + staging), com região e ambiente.

Modo de provisionamento:
- **Docker disponível** (docker compose num host Linux, ou uvicorn no host): cria
  CONTAINERS PostgreSQL REAIS e carrega um schema de negócio por empresa (catálogo
  + tabela transacional) em prod e staging. SQL Console, logs e métricas ao vivo
  funcionam de verdade.
- **Sem Docker** (ex.: Docker Desktop em Mac/Windows): cai para registros
  dados-apenas (STOPPED), para o dashboard ainda mostrar a frota (mapa de
  regiões, cards) — sem tráfego, porque não há banco para consultar.

Executado automaticamente pelo docker compose após as migrations. Idempotente:
instâncias já existentes (por nome+empresa) são puladas, então religar o stack
não recria nada. Também roda à mão, a partir de backend/ com a venv ativa:

    python -m src.seed.demo            # semeia
    python -m src.seed.demo --clear    # remove a frota demo (containers + registros)
"""
import asyncio
import logging
import sys

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
from src.services.instance import create_instance

logger = logging.getLogger(__name__)

DEMO_MARKER = "__demo_fleet__"  # marca as instâncias deste seed (idempotência/teardown)

# Senha única de demonstração. Atende à política (12+ chars, maiúscula, minúscula,
# dígito e símbolo). Dado mock — impresso no log para facilitar o login.
DEMO_PASSWORD = "DemoPass123!"

MEMBER_NAMES = ["ana", "bruno", "carla", "diego"]

# Tamanho-alvo do banco POR INSTÂNCIA (total de pg_database_size), contra o plano
# de 1 GB declarado em COMPANIES. Alvos VARIADOS de propósito: com um valor único
# por ambiente, todos os cards mostravam a mesma barra e a frota parecia de
# brinquedo. Aqui prod ocupa ~37–60% e staging ~14–29% — um espectro que lê como
# "frota real", ainda sem gravar gigabytes por instância. Tunável: ajuste um número
# e o card acompanha, porque os bytes são MEDIDOS por pg_database_size, não
# inventados — a tabela-fato de negócio é quem cresce até o alvo.
_MB = 1024 ** 2
_DB_TARGET_BYTES = {
    "neptune-payments-prod": 620 * _MB,      # ~60%
    "saturn-store-prod": 500 * _MB,          # ~49%
    "jupiter-clothing-prod": 380 * _MB,      # ~37%
    "neptune-payments-staging": 180 * _MB,   # ~18%
    "saturn-store-staging": 300 * _MB,       # ~29%
    "jupiter-clothing-staging": 140 * _MB,   # ~14%
}

# Linhas de negócio por lote de geração. Linhas realistas são mais estreitas que o
# BLOB antigo (~150 B vs ~640 B), então cabem mais por MB; 100k/lote mantém a
# geração rápida e o teto de lotes protege contra loop infinito se pg_database_size
# não subir como esperado (620 MB ÷ ~150 B ≈ 4,3M linhas ≈ 43 lotes).
_FILL_BATCH_ROWS = 100_000
_FILL_MAX_BATCHES = 140

# Tabelas de layouts ANTIGOS do seed, dropadas na migração para o schema de
# negócio (o BLOB `storage_ballast` e os catálogos antigos).
_LEGACY_TABLES = ("storage_ballast", "transactions", "inventory")

# Configuração por empresa: região, admin, o SCHEMA de negócio e as 2 instâncias
# (nome, ambiente, cpu, memória MB, storage GB).
#
# Cada base tem um CATÁLOGO pequeno e curado (dimensão) e uma tabela transacional
# GRANDE (fato) — esta é quem enche o disco até o alvo de `_DB_TARGET_BYTES`,
# gerando linhas de negócio realistas em vez de um BLOB. Toda tabela-fato tem
# `amount` e `created_at`, o contrato que a carga (`workload_simulator`) usa para a
# query pesada "receita por hora". Tudo em inglês (dado de negócio, não UI).
#
#   catalog.seed  — INSERT com VALUES curados (roda uma vez).
#   fact.gen      — INSERT ... SELECT FROM generate_series(1, %s) que referencia o
#                   catálogo por LATERAL; repetido em lotes até o tamanho-alvo.
COMPANIES: dict[str, dict] = {
    "Neptune Payments": {
        "slug": "neptune",
        "region": "sa-east-1",
        "catalog": {
            "name": "merchants",
            "ddl": """
                CREATE TABLE merchants (
                    id       SERIAL PRIMARY KEY,
                    name     TEXT NOT NULL,
                    category TEXT NOT NULL,
                    country  CHAR(2) NOT NULL,
                    mcc      INTEGER NOT NULL
                )
            """,
            "seed": """
                INSERT INTO merchants (name, category, country, mcc) VALUES
                    ('Skyline Electronics', 'Retail', 'US', 5732),
                    ('Harbor Grocery', 'Food & Beverage', 'US', 5411),
                    ('Nimbus Cloud', 'SaaS', 'US', 5734),
                    ('Coastline Airlines', 'Travel', 'GB', 4511),
                    ('Meridian Books', 'Retail', 'GB', 5942),
                    ('Copper Kettle Cafe', 'Food & Beverage', 'BR', 5812),
                    ('Vertex Gaming', 'Gaming', 'US', 5816),
                    ('Aurora Pharmacy', 'Healthcare', 'DE', 5912),
                    ('Ironwood Furniture', 'Retail', 'US', 5712),
                    ('Solstice Streaming', 'Entertainment', 'US', 4899),
                    ('Golden Route Transit', 'Travel', 'BR', 4111),
                    ('Pinecrest Hardware', 'Retail', 'US', 5251),
                    ('Lumen Utilities', 'Utilities', 'PT', 4900),
                    ('Fresh Harvest Market', 'Food & Beverage', 'BR', 5411),
                    ('Quantum Mobile', 'Telecom', 'US', 4814),
                    ('Verdant Gardens', 'Retail', 'GB', 5261),
                    ('Blue Orbit Travel', 'Travel', 'DE', 4722),
                    ('Summit Sports', 'Retail', 'US', 5941),
                    ('Marble Arch Hotel', 'Hospitality', 'GB', 7011),
                    ('Riverside Diner', 'Food & Beverage', 'US', 5812),
                    ('Terrace Apparel', 'Retail', 'BR', 5651),
                    ('Halcyon Studios', 'SaaS', 'US', 5734),
                    ('Northgate Motors', 'Automotive', 'DE', 5511),
                    ('Sable Coffee Roasters', 'Food & Beverage', 'PT', 5499),
                    ('Willowbrook Toys', 'Retail', 'US', 5945),
                    ('Cobalt Fitness', 'Health & Fitness', 'GB', 7997),
                    ('Palermo Trattoria', 'Food & Beverage', 'BR', 5812),
                    ('Zephyr Airlines', 'Travel', 'US', 4511),
                    ('Emberline Bakery', 'Food & Beverage', 'US', 5462),
                    ('Sterling Pay Services', 'Financial', 'GB', 6012)
            """,
        },
        "fact": {
            "name": "payments",
            "ddl": """
                CREATE TABLE payments (
                    id             BIGSERIAL PRIMARY KEY,
                    reference      TEXT NOT NULL,
                    merchant       TEXT NOT NULL,
                    customer_email TEXT NOT NULL,
                    amount         NUMERIC(12,2) NOT NULL,
                    currency       CHAR(3) NOT NULL,
                    method         TEXT NOT NULL,
                    status         TEXT NOT NULL,
                    created_at     TIMESTAMPTZ NOT NULL
                )
            """,
            "gen": """
                INSERT INTO payments
                    (reference, merchant, customer_email, amount, currency, method, status, created_at)
                SELECT
                    'PAY-' || upper(substr(md5(random()::text), 1, 10)),
                    m.name,
                    lower((ARRAY['ava','liam','noah','emma','olivia','ethan','mia','lucas','sophia','leo'])[1 + (random() * 9)::int])
                        || '.' ||
                        lower((ARRAY['smith','jones','brown','wilson','taylor','silva','costa','muller','rossi','park'])[1 + (random() * 9)::int])
                        || (random() * 900 + 100)::int || '@example.com',
                    round((random() * 490 + 4.90)::numeric, 2),
                    (ARRAY['USD','BRL','EUR','GBP'])[1 + (random() * 3)::int],
                    (ARRAY['card','card','card','pix','wallet','boleto','transfer'])[1 + (random() * 6)::int],
                    (ARRAY['captured','captured','captured','captured','pending','refunded','failed','chargeback'])[1 + (random() * 7)::int],
                    now() - (random() * interval '365 days')
                FROM generate_series(1, %s) g
                JOIN LATERAL (
                    SELECT name FROM merchants
                    WHERE id = 1 + ((g + (random() * 1e9)::bigint) %% (SELECT count(*) FROM merchants))::int
                    LIMIT 1
                ) m ON true
            """,
        },
        "instances": [
            ("neptune-payments-prod", Environment.PRODUCTION, 2, 2048, 1),
            ("neptune-payments-staging", Environment.STAGING, 1, 1024, 1),
        ],
    },
    "Saturn Music Store": {
        "slug": "saturn",
        "region": "us-east-1",
        "catalog": {
            "name": "products",
            "ddl": """
                CREATE TABLE products (
                    id         SERIAL PRIMARY KEY,
                    sku        TEXT UNIQUE NOT NULL,
                    name       TEXT NOT NULL,
                    category   TEXT NOT NULL,
                    brand      TEXT NOT NULL,
                    unit_price NUMERIC(10,2) NOT NULL
                )
            """,
            "seed": """
                INSERT INTO products (sku, name, category, brand, unit_price) VALUES
                    ('GUI-STRAT-01', 'Fender Player Stratocaster', 'Guitars', 'Fender', 799.00),
                    ('GUI-LP-STD',   'Gibson Les Paul Standard', 'Guitars', 'Gibson', 2499.00),
                    ('GUI-TELE-02',  'Fender American Telecaster', 'Guitars', 'Fender', 1149.00),
                    ('GUI-SG-STD',   'Gibson SG Standard', 'Guitars', 'Gibson', 1499.00),
                    ('GUI-PRS-SE',   'PRS SE Custom 24', 'Guitars', 'PRS', 899.00),
                    ('BAS-JAZZ-01',  'Fender Jazz Bass', 'Bass', 'Fender', 949.00),
                    ('BAS-PREC-01',  'Fender Precision Bass', 'Bass', 'Fender', 899.00),
                    ('KEY-P125',     'Yamaha P-125 Digital Piano', 'Keyboards', 'Yamaha', 699.00),
                    ('KEY-STAGE3',   'Nord Stage 3 Compact', 'Keyboards', 'Nord', 4299.00),
                    ('KEY-JUNO',     'Roland Juno-DS61 Synth', 'Keyboards', 'Roland', 849.00),
                    ('KEY-MODX',     'Yamaha MODX7 Synth', 'Keyboards', 'Yamaha', 1499.00),
                    ('DRM-TD17',     'Roland TD-17KVX V-Drums', 'Drums', 'Roland', 1699.00),
                    ('DRM-EXPORT',   'Pearl Export EXX Kit', 'Drums', 'Pearl', 899.00),
                    ('DRM-SNARE-01', 'Ludwig Supraphonic Snare', 'Drums', 'Ludwig', 429.00),
                    ('DRM-CYM-A',    'Zildjian A Custom Cymbal Pack', 'Drums', 'Zildjian', 799.00),
                    ('WND-SAX-ALT',  'Yamaha YAS-280 Alto Sax', 'Wind', 'Yamaha', 1199.00),
                    ('WND-TRUMP-01', 'Bach TR300 Trumpet', 'Wind', 'Bach', 649.00),
                    ('WND-CLAR-01',  'Buffet E11 Clarinet', 'Wind', 'Buffet', 899.00),
                    ('STU-SM7B',     'Shure SM7B Microphone', 'Studio', 'Shure', 399.00),
                    ('STU-SM58',     'Shure SM58 Microphone', 'Studio', 'Shure', 99.00),
                    ('STU-SCARL2',   'Focusrite Scarlett 2i2', 'Studio', 'Focusrite', 199.00),
                    ('STU-HD280',    'Sennheiser HD 280 Pro', 'Studio', 'Sennheiser', 129.00),
                    ('STU-KRK5',     'KRK Rokit 5 G4 Monitor', 'Studio', 'KRK', 179.00),
                    ('ACC-STRAP-01', 'Leather Guitar Strap', 'Accessories', 'Levys', 39.00),
                    ('ACC-STAND-01', 'Hercules Guitar Stand', 'Accessories', 'Hercules', 45.00),
                    ('ACC-CABLE-01', 'Mogami Gold 10ft Cable', 'Accessories', 'Mogami', 49.00),
                    ('ACC-CAPO-01',  'G7th Performance Capo', 'Accessories', 'G7th', 59.00),
                    ('ACC-TUNER-01', 'Boss TU-3 Chromatic Tuner', 'Accessories', 'Boss', 99.00),
                    ('AMP-BLUES',    'Fender Blues Junior IV Amp', 'Amplifiers', 'Fender', 699.00),
                    ('AMP-KATANA',   'Boss Katana-100 MkII Amp', 'Amplifiers', 'Boss', 379.00)
            """,
        },
        "fact": {
            "name": "sales",
            "ddl": """
                CREATE TABLE sales (
                    id         BIGSERIAL PRIMARY KEY,
                    order_ref  TEXT NOT NULL,
                    product    TEXT NOT NULL,
                    category   TEXT NOT NULL,
                    brand      TEXT NOT NULL,
                    quantity   INTEGER NOT NULL,
                    unit_price NUMERIC(10,2) NOT NULL,
                    amount     NUMERIC(12,2) NOT NULL,
                    channel    TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """,
            "gen": """
                INSERT INTO sales
                    (order_ref, product, category, brand, quantity, unit_price, amount, channel, created_at)
                SELECT
                    'SO-' || upper(substr(md5(random()::text), 1, 8)),
                    r.name, r.category, r.brand, r.qty, r.unit_price,
                    round((r.qty * r.unit_price)::numeric, 2),
                    (ARRAY['store','online','online'])[1 + (random() * 2)::int],
                    now() - (random() * interval '365 days')
                FROM generate_series(1, %s) g
                JOIN LATERAL (
                    SELECT p.name, p.category, p.brand, p.unit_price,
                           (random() * 2 + 1)::int AS qty
                    FROM products p
                    WHERE p.id = 1 + ((g + (random() * 1e9)::bigint) %% (SELECT count(*) FROM products))::int
                    LIMIT 1
                ) r ON true
            """,
        },
        "instances": [
            ("saturn-store-prod", Environment.PRODUCTION, 2, 2048, 1),
            ("saturn-store-staging", Environment.STAGING, 1, 1024, 1),
        ],
    },
    "Jupiter Clothing": {
        "slug": "jupiter",
        "region": "eu-west-1",
        "catalog": {
            "name": "products",
            "ddl": """
                CREATE TABLE products (
                    id         SERIAL PRIMARY KEY,
                    sku        TEXT UNIQUE NOT NULL,
                    name       TEXT NOT NULL,
                    category   TEXT NOT NULL,
                    size       TEXT NOT NULL,
                    color      TEXT NOT NULL,
                    unit_price NUMERIC(10,2) NOT NULL
                )
            """,
            "seed": """
                INSERT INTO products (sku, name, category, size, color, unit_price) VALUES
                    ('TOP-CREW-S-NVY',  'Merino Crew Sweater', 'Tops', 'S', 'Navy', 89.00),
                    ('TOP-CREW-M-GRY',  'Merino Crew Sweater', 'Tops', 'M', 'Grey', 89.00),
                    ('TOP-OXF-M-WHT',   'Oxford Cotton Shirt', 'Tops', 'M', 'White', 59.00),
                    ('TOP-OXF-L-BLU',   'Oxford Cotton Shirt', 'Tops', 'L', 'Blue', 59.00),
                    ('TOP-TEE-S-BLK',   'Pima Cotton T-Shirt', 'Tops', 'S', 'Black', 29.00),
                    ('TOP-TEE-M-WHT',   'Pima Cotton T-Shirt', 'Tops', 'M', 'White', 29.00),
                    ('TOP-POLO-L-GRN',  'Pique Polo Shirt', 'Tops', 'L', 'Green', 45.00),
                    ('TOP-FLAN-M-RED',  'Brushed Flannel Shirt', 'Tops', 'M', 'Red', 65.00),
                    ('BOT-CHINO-32-KHK','Slim Chino Trousers', 'Bottoms', '32', 'Khaki', 69.00),
                    ('BOT-CHINO-34-NVY','Slim Chino Trousers', 'Bottoms', '34', 'Navy', 69.00),
                    ('BOT-JEAN-32-IND', 'Selvedge Denim Jeans', 'Bottoms', '32', 'Indigo', 119.00),
                    ('BOT-JEAN-34-BLK', 'Selvedge Denim Jeans', 'Bottoms', '34', 'Black', 119.00),
                    ('BOT-SHORT-M-BEI', 'Linen Blend Shorts', 'Bottoms', 'M', 'Beige', 49.00),
                    ('BOT-JOG-L-GRY',   'French Terry Joggers', 'Bottoms', 'L', 'Grey', 55.00),
                    ('OUT-PARKA-M-OLV', 'Waxed Cotton Parka', 'Outerwear', 'M', 'Olive', 199.00),
                    ('OUT-PARKA-L-BLK', 'Waxed Cotton Parka', 'Outerwear', 'L', 'Black', 199.00),
                    ('OUT-BOMB-M-NVY',  'Quilted Bomber Jacket', 'Outerwear', 'M', 'Navy', 149.00),
                    ('OUT-TRENCH-M-TAN','Cotton Trench Coat', 'Outerwear', 'M', 'Tan', 229.00),
                    ('OUT-PUFF-L-BLK',  'Down Puffer Jacket', 'Outerwear', 'L', 'Black', 179.00),
                    ('FOO-SNEAK-42-WHT','Leather Court Sneakers', 'Footwear', '42', 'White', 99.00),
                    ('FOO-SNEAK-44-BLK','Leather Court Sneakers', 'Footwear', '44', 'Black', 99.00),
                    ('FOO-BOOT-43-BRN', 'Suede Chelsea Boots', 'Footwear', '43', 'Brown', 159.00),
                    ('FOO-LOAF-42-TAN', 'Penny Loafers', 'Footwear', '42', 'Tan', 139.00),
                    ('ACC-BELT-M-BRN',  'Full Grain Leather Belt', 'Accessories', 'M', 'Brown', 45.00),
                    ('ACC-SCARF-U-GRY', 'Lambswool Scarf', 'Accessories', 'One Size', 'Grey', 39.00),
                    ('ACC-BEAN-U-NVY',  'Ribbed Wool Beanie', 'Accessories', 'One Size', 'Navy', 25.00),
                    ('ACC-SOCK-U-BLK',  'Merino Sock 3-Pack', 'Accessories', 'One Size', 'Black', 22.00),
                    ('ACC-CAP-U-KHK',   'Cotton Twill Cap', 'Accessories', 'One Size', 'Khaki', 29.00),
                    ('OUT-CARD-M-CAM',  'Shawl Collar Cardigan', 'Outerwear', 'M', 'Camel', 99.00),
                    ('TOP-HOOD-L-GRY',  'Loopback Cotton Hoodie', 'Tops', 'L', 'Grey', 69.00)
            """,
        },
        "fact": {
            "name": "sales",
            "ddl": """
                CREATE TABLE sales (
                    id         BIGSERIAL PRIMARY KEY,
                    order_ref  TEXT NOT NULL,
                    product    TEXT NOT NULL,
                    category   TEXT NOT NULL,
                    size       TEXT NOT NULL,
                    color      TEXT NOT NULL,
                    quantity   INTEGER NOT NULL,
                    unit_price NUMERIC(10,2) NOT NULL,
                    amount     NUMERIC(12,2) NOT NULL,
                    channel    TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """,
            "gen": """
                INSERT INTO sales
                    (order_ref, product, category, size, color, quantity, unit_price, amount, channel, created_at)
                SELECT
                    'ORD-' || upper(substr(md5(random()::text), 1, 8)),
                    r.name, r.category, r.size, r.color, r.qty, r.unit_price,
                    round((r.qty * r.unit_price)::numeric, 2),
                    (ARRAY['store','online','online'])[1 + (random() * 2)::int],
                    now() - (random() * interval '365 days')
                FROM generate_series(1, %s) g
                JOIN LATERAL (
                    SELECT p.name, p.category, p.size, p.color, p.unit_price,
                           (random() * 3 + 1)::int AS qty
                    FROM products p
                    WHERE p.id = 1 + ((g + (random() * 1e9)::bigint) %% (SELECT count(*) FROM products))::int
                    LIMIT 1
                ) r ON true
            """,
        },
        "instances": [
            ("jupiter-clothing-prod", Environment.PRODUCTION, 2, 2048, 1),
            ("jupiter-clothing-staging", Environment.STAGING, 1, 1024, 1),
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


def _seed_business_data(inst: DatabaseInstance, cfg: dict) -> None:
    """
    Deixar o banco com um schema de negócio REAL e ocupado até o alvo do ambiente.

    Um PostgreSQL recém-provisionado ocupa ~8 MB. Contra qualquer plano plausível
    isso arredonda para 0%, e a barra do card fica morta. Antes o volume vinha de
    um BLOB opaco (`storage_ballast`) — que aparecia cru na SQL Console e denunciava
    a demo. Agora o volume é a própria tabela transacional do negócio (payments /
    sales): as linhas existem de verdade, `pg_database_size` mede o que está no
    disco, o backup as carrega e a SQL Console mostra dados que fazem sentido.

    Migração + idempotência pela EXISTÊNCIA da tabela-fato:
    - Fato ausente → base no layout antigo (ou vazia): dropa o legado (BLOB +
      catálogos antigos) e quaisquer tabelas do schema novo, recria catálogo + fato
      e semeia o catálogo curado (uma vez).
    - Fato presente → só completa o preenchimento até o alvo (relê o tamanho a cada
      lote e para ao alcançar), então reexecutar o seed não engorda o banco.
    """
    target = _DB_TARGET_BYTES.get(inst.name)
    if target is None or not inst.connection_uri:
        return

    catalog, fact = cfg["catalog"], cfg["fact"]
    with psycopg.connect(decrypt_value(inst.connection_uri), autocommit=True) as conn:
        fact_exists = conn.execute(
            "SELECT to_regclass(%s) IS NOT NULL", (fact["name"],)
        ).fetchone()[0]
        if not fact_exists:
            # Estado limpo: derruba o legado (BLOB + catálogos antigos) e o schema
            # novo (caso um seed anterior tenha parado no meio), depois recria.
            drop = ", ".join(_LEGACY_TABLES + (catalog["name"], fact["name"]))
            conn.execute(f"DROP TABLE IF EXISTS {drop} CASCADE")
            conn.execute(catalog["ddl"])
            conn.execute(catalog["seed"])
            conn.execute(fact["ddl"])
        _fill_to_target(conn, fact["gen"], target, inst.name)


def _fill_to_target(conn, gen_sql: str, target: int, inst_name: str) -> None:
    """Gera linhas de negócio em lotes até `pg_database_size` alcançar o alvo."""
    for _ in range(_FILL_MAX_BATCHES):
        size = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        if size >= target:
            break
        conn.execute(gen_sql, (_FILL_BATCH_ROWS,))
    else:
        logger.warning(
            "Seed demo: %s parou no teto de lotes sem atingir %d bytes", inst_name, target
        )


def _reset_query_stats(inst: DatabaseInstance) -> None:
    """
    Zera o pg_stat_statements depois de semear.

    As queries de PROVISIONAMENTO — o COPY do dataset e os INSERTs do lastro —
    levam centenas de milissegundos e ficam gravadas para sempre na view, que
    agrega por fingerprint desde o último reset. Com elas dentro, o p99 da
    instância fica cravado em ~900ms: um número real, mas que descreve o seed,
    não o serviço. Zerando aqui, os percentis passam a medir só o tráfego que a
    instância de fato atende.
    """
    if not inst.connection_uri:
        return
    try:
        with psycopg.connect(decrypt_value(inst.connection_uri), autocommit=True) as conn:
            conn.execute("SELECT pg_stat_statements_reset()")
    except Exception as exc:  # noqa: BLE001 — sem a extensão, não há o que zerar
        logger.debug("Seed demo: pg_stat_statements_reset em %s: %s", inst.name, exc)


def _seed_real(db, company: Company, admin: User, cfg: dict) -> None:
    """Provisiona containers reais e carrega o schema de negócio em prod E staging."""
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
        elif inst.storage_gb != storage:
            # Instância de um seed anterior, com o plano antigo: reconcilia. Sem
            # isto a barra de storage do card continuaria calculada sobre uma
            # capacidade que o seed não declara mais.
            inst.storage_gb = storage
            db.commit()
        # Prod e staging ganham o MESMO schema (staging só com menos linhas): uma
        # staging que mostrasse só o BLOB não parecia uma cópia do app.
        if inst.status == InstanceStatus.RUNNING:
            _seed_business_data(inst, cfg)

    # Por último, com o dataset e o lastro já gravados: as estatísticas de query
    # começam do zero, medindo serviço em vez de provisionamento.
    for name, _env, *_ in cfg["instances"]:
        inst = _existing_instance(db, name, company.id)
        if inst is not None and inst.status == InstanceStatus.RUNNING:
            _reset_query_stats(inst)


def _seed_data_only(db, company: Company, cfg: dict) -> None:
    """Insere registros STOPPED (sem Docker). Se o usuário rodar a simulação,
    o backfill histórico ainda popula estas instâncias — mas não haverá
    tráfego, porque não existe banco para consultar."""
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
    # A frota nasce VIVA: o histórico sintético (24h de métricas, uptime, backups,
    # alertas, manutenção, audit) é semeado agora, no boot — o dashboard mostra
    # uma plataforma robusta já no primeiro login, sem ninguém clicar em nada. O
    # botão "Ver ao vivo" em /demo só amplifica isso por ~1 min.
    _enrich_boot(db)
    logger.info("Seed demo: concluído. Login: qualquer usuário @{neptune,saturn,jupiter}.example / %s", DEMO_PASSWORD)


def _enrich_boot(db) -> None:
    """
    Popula a frota demo com histórico logo após o provisionamento.

    Uma coleta real primeiro, para o backfill de 24h ancorar no tamanho de fato
    medido (senão `enrich_fleet` cai para uma fração arbitrária da capacidade, e
    a barra de storage não bate com o lastro gravado). Depois `enrich_fleet`
    (idempotente: reruns não duplicam).

    Best-effort: falha de coleta numa instância só a deixa com o backfill de
    fallback — o boot nunca falha por isto.
    """
    from src.models.instance_status_history import InstanceStatusHistory
    from src.services.metrics import collect_and_store
    from src.seed import history

    demos = (
        db.query(DatabaseInstance)
        .filter(
            DatabaseInstance.notes == DEMO_MARKER,
            DatabaseInstance.deleted_at.is_(None),
        )
        .all()
    )
    for inst in demos:
        if inst.status != InstanceStatus.RUNNING or not inst.connection_uri:
            continue
        try:
            collect_and_store(db, inst)
        except Exception as exc:  # noqa: BLE001 — o boot não pode falhar por isto
            db.rollback()
            logger.warning("Seed demo: coleta inicial em %s falhou: %s", inst.name, exc)

    # O provisionamento já gravou linhas pending→provisioning→running no histórico
    # de status. Sem removê-las, o guard de `enrich_fleet::_backdate_status`
    # (`not _has(InstanceStatusHistory)`) pula o retroagir do created_at, e o KPI
    # de uptime de 30 dias mede uma janela de segundos → percentuais absurdos.
    # Zeramos aqui para o enrich semear a idade real (RUNNING desde ~45 dias).
    demo_ids = [i.id for i in demos]
    if demo_ids:
        db.query(InstanceStatusHistory).filter(
            InstanceStatusHistory.instance_id.in_(demo_ids)
        ).delete(synchronize_session=False)
        db.commit()

    history.enrich_fleet(db)


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
