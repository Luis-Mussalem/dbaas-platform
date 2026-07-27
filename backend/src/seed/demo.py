"""
Seed for the demo (multi-tenant) fleet — the fleet a clean clone
delivers ready to explore.

What this seed creates is REAL: actual companies, users, and PostgreSQL
containers with loaded data. It also leaves the fleet ALIVE by the end of boot:
it seeds synthetic history (24h of metrics, uptime, backups, alerts,
maintenance, audit — via `seed/history.enrich_fleet`) and the load generator
(`services/workload_simulator.py`) keeps a continuous baseline load, so the
dashboard shows a robust, live platform right on the first login, without
anyone needing to click anything.

Creates, idempotently:
- 3 fictitious companies + 5 users each (1 company admin + 4 members), all
  with the same demo password (mock data, no real secret).
- 2 instances per company (prod + staging), with region and environment.

Provisioning mode:
- **Docker available** (docker compose on a Linux host, or uvicorn on the host): creates
  REAL PostgreSQL CONTAINERS and loads a business schema per company (catalog
  + transactional table) in prod and staging. The SQL Console, logs, and live
  metrics actually work.
- **No Docker** (e.g. Docker Desktop on Mac/Windows): falls back to
  data-only records (STOPPED), so the dashboard still shows the fleet (region
  map, cards) — without traffic, since there's no database to query.

Run automatically by docker compose after the migrations. Idempotent:
instances that already exist (by name+company) are skipped, so restarting the
stack doesn't recreate anything. Also runs by hand, from backend/ with the venv active:

    python -m src.seed.demo            # seeds
    python -m src.seed.demo --clear    # removes the demo fleet (containers + records)
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

DEMO_MARKER = "__demo_fleet__"  # marks the instances created by this seed (idempotency/teardown)

# Single demo password. Meets the policy (12+ chars, uppercase, lowercase,
# digit, and symbol). Mock data — printed to the log to make logging in easier.
DEMO_PASSWORD = "DemoPass123!"

MEMBER_NAMES = ["ana", "bruno", "carla", "diego"]

# Target database size PER INSTANCE (total pg_database_size), against the 1 GB
# plan declared in COMPANIES. VARIED targets on purpose: with a single value
# per environment, every card showed the same bar and the fleet looked like a
# toy. Here prod occupies ~37-60% and staging ~14-29% — a spread that reads as
# a "real fleet", while still not writing gigabytes per instance. Tunable: adjust a
# number and the card follows, because the bytes are MEASURED by pg_database_size, not
# made up — the business fact table is what grows to the target.
_MB = 1024 ** 2
_DB_TARGET_BYTES = {
    "neptune-payments-prod": 620 * _MB,      # ~60%
    "saturn-store-prod": 500 * _MB,          # ~49%
    "jupiter-clothing-prod": 380 * _MB,      # ~37%
    "neptune-payments-staging": 180 * _MB,   # ~18%
    "saturn-store-staging": 300 * _MB,       # ~29%
    "jupiter-clothing-staging": 140 * _MB,   # ~14%
}

# Business rows per generation batch. Realistic rows are narrower than the
# old BLOB (~150 B vs ~640 B), so more fit per MB; 100k/batch keeps
# generation fast and the batch cap guards against an infinite loop if pg_database_size
# doesn't climb as expected (620 MB ÷ ~150 B ≈ 4.3M rows ≈ 43 batches).
_FILL_BATCH_ROWS = 100_000
_FILL_MAX_BATCHES = 140

# Tables from the seed's OLD layouts, dropped in the migration to the business
# schema (the `storage_ballast` BLOB and the old catalogs).
_LEGACY_TABLES = ("storage_ballast", "transactions", "inventory")

# Per-company configuration: region, admin, the business SCHEMA, and the 2 instances
# (name, environment, cpu, memory MB, storage GB).
#
# Each database has a small, curated CATALOG (dimension) and a LARGE transactional
# table (fact) — this is what fills the disk up to the `_DB_TARGET_BYTES` target,
# generating realistic business rows instead of a BLOB. Every fact table has
# `amount` and `created_at`, the contract the load (`workload_simulator`) uses for the
# heavy "hourly revenue" query. Everything in English (business data, not UI).
#
#   catalog.seed  — INSERT with curated VALUES (runs once).
#   fact.gen      — INSERT ... SELECT FROM generate_series(1, %s) that references the
#                   catalog via LATERAL; repeated in batches up to the target size.
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
# Companies and users
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
# Real provisioning vs. data-only fallback
# --------------------------------------------------------------------------- #
def _provisioner_available() -> bool:
    """True if the Docker daemon is reachable (otherwise, data-only seed).

    get_provisioner() hits the daemon right at construction (via _ensure_network), so it
    raises docker.errors.DockerException if Docker isn't reachable.
    """
    try:
        from src.services.provisioning import get_provisioner

        get_provisioner()
        return True
    except Exception as exc:
        logger.info("Demo seed: Docker unavailable (%s) — using data-only mode.", exc)
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
    Leaves the database with a REAL business schema, filled up to the environment's target.

    A freshly provisioned PostgreSQL occupies ~8 MB. Against any plausible plan
    that rounds to 0%, and the card's bar looks dead. The volume used to come from
    an opaque BLOB (`storage_ballast`) — which showed up raw in the SQL Console and gave
    the demo away. Now the volume is the business's actual transactional table (payments /
    sales): the rows genuinely exist, `pg_database_size` measures what's on
    disk, the backup carries them, and the SQL Console shows data that makes sense.

    Migration + idempotency via the EXISTENCE of the fact table:
    - Fact missing → database on the old layout (or empty): drops the legacy (BLOB +
      old catalogs) and any tables from the new schema, recreates catalog + fact,
      and seeds the curated catalog (once).
    - Fact present → just tops up the fill to the target (rereads the size on each
      batch and stops once reached), so rerunning the seed doesn't bloat the database.
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
            # Clean state: tears down the legacy (BLOB + old catalogs) and the new
            # schema (in case a previous seed stopped halfway through), then recreates.
            drop = ", ".join(_LEGACY_TABLES + (catalog["name"], fact["name"]))
            conn.execute(f"DROP TABLE IF EXISTS {drop} CASCADE")
            conn.execute(catalog["ddl"])
            conn.execute(catalog["seed"])
            conn.execute(fact["ddl"])
        _fill_to_target(conn, fact["gen"], target, inst.name)


def _fill_to_target(conn, gen_sql: str, target: int, inst_name: str) -> None:
    """Generates business rows in batches until `pg_database_size` reaches the target."""
    for _ in range(_FILL_MAX_BATCHES):
        size = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        if size >= target:
            break
        conn.execute(gen_sql, (_FILL_BATCH_ROWS,))
    else:
        logger.warning(
            "Demo seed: %s stopped at the batch cap without reaching %d bytes", inst_name, target
        )


def _reset_query_stats(inst: DatabaseInstance) -> None:
    """
    Resets pg_stat_statements after seeding.

    The PROVISIONING queries — the dataset COPY and the ballast INSERTs —
    take hundreds of milliseconds and stay recorded forever in the view, which
    aggregates by fingerprint since the last reset. With them still in there, the
    instance's p99 stays pinned at ~900ms: a real number, but one that describes the seed,
    not the service. Resetting here, the percentiles go on to measure only the traffic the
    instance actually serves.
    """
    if not inst.connection_uri:
        return
    try:
        with psycopg.connect(decrypt_value(inst.connection_uri), autocommit=True) as conn:
            conn.execute("SELECT pg_stat_statements_reset()")
    except Exception as exc:  # noqa: BLE001 — without the extension, there's nothing to reset
        logger.debug("Demo seed: pg_stat_statements_reset on %s: %s", inst.name, exc)


def _seed_real(db, company: Company, admin: User, cfg: dict) -> None:
    """Provisions real containers and loads the business schema in prod AND staging."""
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
            logger.info("Demo seed: provisioning %s ...", name)
            inst = asyncio.run(create_instance(db, data, admin))
            logger.info("Demo seed:   -> %s at %s:%s", inst.status.value, inst.host, inst.port)
        elif inst.storage_gb != storage:
            # Instance from a previous seed, with the old plan: reconcile it. Without
            # this the card's storage bar would keep being calculated against a
            # capacity the seed no longer declares.
            inst.storage_gb = storage
            db.commit()
        # Prod and staging get the SAME schema (staging just with fewer rows): a
        # staging that only showed the BLOB didn't look like a copy of the app.
        if inst.status == InstanceStatus.RUNNING:
            _seed_business_data(inst, cfg)

    # Last, with the dataset and ballast already written: query statistics
    # start from zero, measuring service instead of provisioning.
    for name, _env, *_ in cfg["instances"]:
        inst = _existing_instance(db, name, company.id)
        if inst is not None and inst.status == InstanceStatus.RUNNING:
            _reset_query_stats(inst)


def _seed_data_only(db, company: Company, cfg: dict) -> None:
    """Inserts STOPPED records (no Docker). If the user runs the simulation,
    the historical backfill still populates these instances — but there will be no
    traffic, since there's no database to query."""
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
            connection_uri=None,  # demo — nothing actually connects
            notes=DEMO_MARKER,
            company_id=company.id,
        )
        db.add(inst)
        db.commit()
        db.refresh(inst)
        logger.info("Demo seed: %s (data-only, %s, %s)", name, cfg["region"], env.value)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def seed(db) -> None:
    can_provision = _provisioner_available()
    mode = "real containers" if can_provision else "data-only"
    logger.info("Demo seed: starting (%s).", mode)
    for company_name, cfg in COMPANIES.items():
        company, admin = _seed_company_and_users(db, company_name, cfg["slug"])
        if can_provision:
            _seed_real(db, company, admin, cfg)
        else:
            _seed_data_only(db, company, cfg)
    # The fleet is born ALIVE: synthetic history (24h of metrics, uptime, backups,
    # alerts, maintenance, audit) is seeded right now, at boot — the dashboard shows
    # a robust platform right on the first login, without anyone clicking anything. The
    # "View live" button on /demo just amplifies this for ~1 min.
    _enrich_boot(db)
    logger.info("Demo seed: done. Login: any user @{neptune,saturn,jupiter}.example / %s", DEMO_PASSWORD)


def _enrich_boot(db) -> None:
    """
    Populates the demo fleet with history right after provisioning.

    A real collection first, so the 24h backfill anchors on the actually
    measured size (otherwise `enrich_fleet` falls back to an arbitrary fraction of the
    capacity, and the storage bar doesn't match the recorded ballast). Then `enrich_fleet`
    (idempotent: reruns don't duplicate).

    Best-effort: a collection failure on one instance just leaves it with the fallback
    backfill — boot never fails because of this.
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
        except Exception as exc:  # noqa: BLE001 — boot must not fail because of this
            db.rollback()
            logger.warning("Demo seed: initial collection on %s failed: %s", inst.name, exc)

    # Provisioning already wrote pending→provisioning→running rows into the status
    # history. Without removing them, the `enrich_fleet::_backdate_status` guard
    # (`not _has(InstanceStatusHistory)`) skips backdating created_at, and the 30-day
    # uptime KPI measures a window of seconds → absurd percentages.
    # We clear it here so enrich can seed the real age (RUNNING for ~45 days).
    demo_ids = [i.id for i in demos]
    if demo_ids:
        db.query(InstanceStatusHistory).filter(
            InstanceStatusHistory.instance_id.in_(demo_ids)
        ).delete(synchronize_session=False)
        db.commit()

    history.enrich_fleet(db)


def clear(db) -> int:
    """Removes the demo fleet (containers, if any, + records + metrics + companies)."""
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
                    logger.warning("Demo seed: deleting container %s failed: %s", inst.name, exc)
            db.query(Metric).filter(Metric.instance_id == inst.id).delete(synchronize_session=False)
            # Backups and schedules reference instance_id without an FK — they don't fall
            # under the instance's DELETE cascade (alerts, maintenance, and status_history
            # do, since they have an FK ON DELETE CASCADE). Remove them by hand.
            db.query(Backup).filter(Backup.instance_id == inst.id).delete(synchronize_session=False)
            db.query(BackupSchedule).filter(BackupSchedule.instance_id == inst.id).delete(synchronize_session=False)
            db.delete(inst)
            removed += 1
        db.commit()
    for company_name, cfg in COMPANIES.items():
        company = db.query(Company).filter(Company.name == company_name).first()
        if company is None:
            continue
        # Audit logs have an FK SET NULL to company — delete them explicitly
        # (otherwise orphans with a null company_id would remain after the company's delete).
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
            logger.info("Demo seed: removed %d instances and the 3 demo companies.", n)
        else:
            seed(db)
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run(clear_only="--clear" in sys.argv)
