from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.core.config import settings

# O pool padrão do SQLAlchemy (5 + 10 de overflow) é apertado para esta
# aplicação: oito loops de background abrem sessões próprias em paralelo com os
# requests HTTP, e durante a simulação de uso todos eles aceleram para 5s. Com o
# pool cheio, `SessionLocal()` fica esperando até `pool_timeout` (30s por
# padrão) e o efeito aparece como uma pausa inexplicável — não como um erro.
# pool_pre_ping descarta conexões que o servidor derrubou (restart do Postgres).
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