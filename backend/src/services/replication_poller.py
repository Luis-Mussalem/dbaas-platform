import asyncio
import logging
from collections import defaultdict

from src.core.database import SessionLocal
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.replica import Replica, ReplicationState
from src.services.metrics import get_connection

logger = logging.getLogger(__name__)

# Intervalo entre ciclos de medição de lag
_POLL_INTERVAL_SECONDS = 30

# Acima deste atraso (1 segmento WAL = 16 MiB) a réplica é considerada em CATCHUP,
# não em STREAMING estável — sinaliza que ainda está alcançando o primário.
_CATCHUP_THRESHOLD_BYTES = 16 * 1024 * 1024

# pg_stat_replication vive no PRIMÁRIO e lista cada standby conectado. Medimos o
# atraso de replay em bytes (quanto o standby está atrás do WAL atual) e em
# segundos (replay_lag). Ordena pelo pior atraso primeiro.
_LAG_QUERY = """
    SELECT
        pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)::bigint AS lag_bytes,
        EXTRACT(EPOCH FROM replay_lag)::float AS lag_seconds
    FROM pg_stat_replication
    ORDER BY replay_lag DESC NULLS LAST
"""


def poll_replication_once() -> None:
    """
    Atualizar estado e lag de cada réplica ativa consultando o primário.

    Mesmo padrão dos demais pollers: SessionLocal() próprio, try/rollback por
    grupo (uma réplica problemática não derruba as outras), finally: close.

    Simplificação assumida: um primário costuma ter um standby. Quando há mais de
    uma réplica no mesmo primário, aplicamos o pior lag observado a todas — sem
    tentar casar linha↔réplica por application_name (fora do escopo do projeto).
    """
    db = SessionLocal()
    try:
        active = (
            db.query(Replica)
            .filter(
                Replica.replication_state.notin_(
                    [ReplicationState.PROMOTED, ReplicationState.FAILED]
                )
            )
            .all()
        )

        by_primary: dict = defaultdict(list)
        for replica in active:
            by_primary[replica.primary_instance_id].append(replica)

        for primary_id, group in by_primary.items():
            try:
                primary = (
                    db.query(DatabaseInstance)
                    .filter(
                        DatabaseInstance.id == primary_id,
                        DatabaseInstance.deleted_at.is_(None),
                        DatabaseInstance.connection_uri.isnot(None),
                    )
                    .first()
                )
                # Primário indisponível → não há como medir; marca desconectado.
                if not primary or primary.status != InstanceStatus.RUNNING:
                    for replica in group:
                        replica.replication_state = ReplicationState.DISCONNECTED
                    db.commit()
                    continue

                with get_connection(primary) as conn:
                    with conn.cursor() as cur:
                        cur.execute(_LAG_QUERY)
                        rows = cur.fetchall()

                if rows:
                    lag_bytes, lag_seconds = rows[0]
                    lag_bytes = int(lag_bytes) if lag_bytes is not None else None
                    lag_seconds = float(lag_seconds) if lag_seconds is not None else None
                    state = (
                        ReplicationState.CATCHUP
                        if (lag_bytes or 0) > _CATCHUP_THRESHOLD_BYTES
                        else ReplicationState.STREAMING
                    )
                    for replica in group:
                        replica.lag_bytes = lag_bytes
                        replica.lag_seconds = lag_seconds
                        replica.replication_state = state
                else:
                    # Sem linhas no primário → nenhum standby transmitindo.
                    for replica in group:
                        replica.replication_state = ReplicationState.DISCONNECTED
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.exception(
                    "Erro ao medir replicação do primário %s: %s", primary_id, exc
                )
    finally:
        db.close()


async def replication_polling_loop(stop_event: asyncio.Event) -> None:
    """
    Loop async que executa poll_replication_once() a cada _POLL_INTERVAL_SECONDS.

    Mesmo shutdown limpo dos demais pollers (asyncio.wait_for sobre o stop_event);
    o trabalho bloqueante (SQL na plataforma + psycopg no primário) vai para o
    thread pool via asyncio.to_thread para não travar o event loop.
    """
    logger.info(
        "Replication poller iniciado (intervalo: %ds)", _POLL_INTERVAL_SECONDS
    )

    while not stop_event.is_set():
        try:
            await asyncio.to_thread(poll_replication_once)
        except Exception as exc:
            logger.exception("Erro no ciclo de medição de replicação: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_POLL_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass

    logger.info("Replication poller encerrado")
