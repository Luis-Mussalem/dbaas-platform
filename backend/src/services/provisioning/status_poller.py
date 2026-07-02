import asyncio
import logging

from sqlalchemy.orm import Session

from src.core.database import SessionLocal
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.services.auth import cleanup_expired_tokens
from src.services.instance import sync_connection_port
from src.services.provisioning.base import ProvisionerBase
from src.services.status_history import record_status_change
from src.services.provisioning.factory import get_provisioner
from src.services.provisioning.types import ProvisionerStatus

logger = logging.getLogger(__name__)

# Intervalo em segundos entre cada ciclo de polling
_POLL_INTERVAL_SECONDS = 30

# Limpeza de tokens expirados: a cada N ciclos de poll (30s × 2880 = 24h)
_TOKEN_CLEANUP_EVERY_N_CYCLES = 2880
_poll_cycle_counter = 0


def _reconcile_instance(
    db: Session, provisioner: ProvisionerBase, instance: DatabaseInstance
) -> None:
    """
    Reconciliar o estado de UMA instância com o que o Docker reporta.

    Aplicado às instâncias que DEVEM estar rodando (RUNNING e FAILED):

    - container RUNNING → garante que a porta publicada bate com o banco
      (o Docker republica porta nova ao religar o container após um restart do
      host) e, se a instância estava FAILED, auto-recupera para RUNNING.
    - container STOPPED → existe mas parou (host/Docker reiniciou, OOM, crash).
      Tenta religar; no sucesso ressincroniza a porta e volta a RUNNING, na
      falha marca FAILED (e tenta de novo no próximo ciclo).
    - container NOT_FOUND/ERROR → sumiu de vez. Se estava RUNNING marca FAILED
      para o operador investigar; se já era FAILED deixa como está (não há o que
      recuperar — re-provisionar criaria um banco vazio).
    """
    infra_status = provisioner.get_status(instance.id)

    if infra_status == ProvisionerStatus.RUNNING:
        changed = False
        port = provisioner.get_port(instance.id)
        if port is not None and port != instance.port:
            sync_connection_port(instance, port)
            changed = True
        if instance.status != InstanceStatus.RUNNING:
            logger.info(
                "Instância %s recuperada: container voltou a rodar", instance.id
            )
            record_status_change(db, instance, InstanceStatus.RUNNING)
            changed = True
        if changed:
            db.commit()

    elif infra_status == ProvisionerStatus.STOPPED:
        logger.warning(
            "Instância %s tem container parado — tentando religar", instance.id
        )
        try:
            new_port = provisioner.start(instance.id)
        except Exception as exc:
            logger.error("Falha ao religar instância %s: %s", instance.id, exc)
            if instance.status != InstanceStatus.FAILED:
                record_status_change(db, instance, InstanceStatus.FAILED)
                db.commit()
            return
        sync_connection_port(instance, new_port)
        # DB pode já estar RUNNING (container caíra sem o banco saber); só
        # registra a transição se o status realmente mudou (evita linha redundante).
        if instance.status != InstanceStatus.RUNNING:
            record_status_change(db, instance, InstanceStatus.RUNNING)
        db.commit()
        logger.info("Instância %s religada com sucesso (porta %d)", instance.id, new_port)

    else:  # NOT_FOUND ou ERROR
        if instance.status == InstanceStatus.RUNNING:
            logger.warning(
                "Instância %s está RUNNING no banco mas o container reporta '%s' "
                "— marcando como FAILED",
                instance.id,
                infra_status.value,
            )
            record_status_change(db, instance, InstanceStatus.FAILED)
            db.commit()


def poll_once() -> None:
    """
    Reconciliação síncrona de todas as instâncias que devem estar rodando.

    Por que síncrono?
    Esta função é chamada via asyncio.to_thread() do loop async, então pode
    fazer operações bloqueantes (consultas SQL + chamadas Docker API) sem
    travar o event loop que processa os requests HTTP.

    Por que SessionLocal() diretamente e não get_db()?
    get_db() é um gerador FastAPI projetado para ser usado como Depends()
    dentro do contexto de um request HTTP. O poller roda fora desse contexto
    (é uma task de background), então cria sua própria Session e a fecha
    manualmente no bloco finally.

    Quais instâncias reconciliamos:
    - RUNNING e FAILED → o estado desejado é "rodando", então reconciliamos
      (inclui auto-recuperar instâncias que caíram num restart do Docker).
    - STOPPED → parada intencional do operador; não tocamos.
    - DELETING/DELETED/PENDING/PROVISIONING → estados transitórios ou finais
      gerenciados por outros fluxos; o poller os ignora.

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
                    [InstanceStatus.RUNNING, InstanceStatus.FAILED]
                ),
                DatabaseInstance.deleted_at.is_(None),
            )
            .all()
        )

        for instance in instances:
            try:
                _reconcile_instance(db, provisioner, instance)
            except Exception as exc:
                db.rollback()
                logger.exception(
                    "Erro ao reconciliar a instância %s: %s", instance.id, exc
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
