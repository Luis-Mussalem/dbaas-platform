import asyncio
import logging
from datetime import datetime, timezone

from src.core.database import SessionLocal
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.services.auth import cleanup_expired_tokens
from src.services.provisioning.factory import get_provisioner
from src.services.provisioning.types import ProvisionerStatus

logger = logging.getLogger(__name__)

# Intervalo em segundos entre cada ciclo de polling
_POLL_INTERVAL_SECONDS = 30

# Limpeza de tokens expirados: a cada N ciclos de poll (30s × 2880 = 24h)
_TOKEN_CLEANUP_EVERY_N_CYCLES = 2880
_poll_cycle_counter = 0


def poll_once() -> None:
    """
    Verificação síncrona de saúde de todas as instâncias RUNNING e STOPPED.

    Por que síncrono?
    Esta função é chamada via asyncio.to_thread() do loop async, então pode
    fazer operações bloqueantes (consultas SQL + chamadas Docker API) sem
    travar o event loop que processa os requests HTTP.

    Por que SessionLocal() diretamente e não get_db()?
    get_db() é um gerador FastAPI projetado para ser usado como Depends()
    dentro do contexto de um request HTTP. O poller roda fora desse contexto
    (é uma task de background), então cria sua própria Session e a fecha
    manualmente no bloco finally.

    Lógica de detecção de falha:
    - RUNNING no banco mas container reporta STOPPED/NOT_FOUND/ERROR
      → o container parou inesperadamente (OOM, crash, reinicialização)
      → marcamos como FAILED para o operador investigar
    - STOPPED no banco mas container reporta RUNNING
      → harmless inconsistência (não deve ocorrer em operação normal)
      → deixamos como está (não forçamos mudanças sem investigar)

    Limpeza de TokenBlacklist:
    - A cada _TOKEN_CLEANUP_EVERY_N_CYCLES ciclos (~24h), remove tokens
      expirados da blacklist. Tokens expirados são inválidos por definição
      (JWT rejeita por 'exp'), então mantê-los só desperdiça espaço.
    """
    global _poll_cycle_counter
    _poll_cycle_counter += 1

    provisioner = get_provisioner()
    db = SessionLocal()
    try:
        instances = (
            db.query(DatabaseInstance)
            .filter(
                DatabaseInstance.status.in_(
                    [InstanceStatus.RUNNING, InstanceStatus.STOPPED]
                ),
                DatabaseInstance.deleted_at.is_(None),
            )
            .all()
        )

        for instance in instances:
            try:
                infra_status = provisioner.get_status(instance.id)

                # Container que deveria estar rodando, mas não está
                if instance.status == InstanceStatus.RUNNING and infra_status in (
                    ProvisionerStatus.NOT_FOUND,
                    ProvisionerStatus.STOPPED,
                    ProvisionerStatus.ERROR,
                ):
                    logger.warning(
                        "Instância %s está RUNNING no banco mas o container "
                        "reporta '%s' — marcando como FAILED",
                        instance.id,
                        infra_status.value,
                    )
                    instance.status = InstanceStatus.FAILED
                    db.commit()

            except Exception as exc:
                logger.exception(
                    "Erro ao fazer poll da instância %s: %s", instance.id, exc
                )

        # Limpeza periódica de tokens expirados da blacklist
        if _poll_cycle_counter % _TOKEN_CLEANUP_EVERY_N_CYCLES == 0:
            try:
                removed = cleanup_expired_tokens(db)
                if removed:
                    logger.info("TokenBlacklist cleanup: %d expired entries removed", removed)
            except Exception as exc:
                logger.warning("TokenBlacklist cleanup failed: %s", exc)

    finally:
        db.close()


async def status_polling_loop(stop_event: asyncio.Event) -> None:
    """
    Loop async que executa poll_once() a cada _POLL_INTERVAL_SECONDS.

    Shutdown limpo via stop_event:
    Em vez de cancelar a task abruptamente (que poderia deixar uma Session
    aberta ou um commit no meio), usamos asyncio.wait_for(stop_event.wait()).
    Quando o lifespan do FastAPI chama stop_event.set() no encerramento:
    - Se estiver esperando o próximo ciclo → wait_for retorna imediatamente
    - O while verifica stop_event.is_set() → sai do loop
    - A task termina graciosamente

    poll_once() é síncrono (SQL + Docker API = I/O bloqueante).
    asyncio.to_thread() roda em thread pool, liberando o event loop para
    continuar processando requests HTTP durante o polling.
    """
    logger.info(
        "Status poller iniciado (intervalo: %ds)", _POLL_INTERVAL_SECONDS
    )

    while not stop_event.is_set():
        try:
            await asyncio.to_thread(poll_once)
        except Exception as exc:
            logger.exception("Erro no ciclo de polling: %s", exc)

        # Aguardar o intervalo OU o sinal de shutdown — o que vier primeiro
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=_POLL_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            pass  # Normal — intervalo expirou, próximo ciclo de poll

    logger.info("Status poller encerrado")
