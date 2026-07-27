from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.core.config import settings

# SQLAlchemy's default pool (5 + 10 overflow) is tight for this
# application: eight background loops open their own sessions in parallel with
# HTTP requests, and during the usage simulation all of them speed up to 5s. With the
# pool full, `SessionLocal()` waits until `pool_timeout` (30s by
# default) and the effect shows up as an unexplained pause — not as an error.
# pool_pre_ping discards connections the server has dropped (Postgres restart).
engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=15,
    max_overflow=20,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()