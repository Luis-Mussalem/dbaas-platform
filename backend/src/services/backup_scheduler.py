import asyncio
import logging
from datetime import datetime, timezone

from src.core.database import SessionLocal
from src.models.backup import BackupSchedule, BackupStrategy, BackupType
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.services.backup import (
    advance_schedule,
    apply_retention,
    create_logical_backup,
    create_physical_backup,
)

logger = logging.getLogger(__name__)


def poll_schedules_once() -> None:
    """
    Verifica todos os BackupSchedules ativos com next_run_at <= agora.
    Para cada um, executa o backup e avança o schedule para a próxima execução.

    Por que sync com SessionLocal() direto (e não Depends(get_db))?
    Este código roda fora do contexto de uma request FastAPI. Não há como usar
    a dependency injection do FastAPI aqui. Criamos e fechamos a sessão manualmente.

    Por que capturar Exception por schedule em vez de deixar propagar?
    Se o backup de uma instância falhar (instância offline, disco cheio, etc.),
    o poller deve continuar verificando as outras instâncias. Uma falha não pode
    derrubar os backups das demais.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        due_schedules = (
            db.query(BackupSchedule)
            .filter(
                BackupSchedule.is_active.is_(True),
                BackupSchedule.next_run_at.isnot(None),
                BackupSchedule.next_run_at <= now,
            )
            .all()
        )

        if not due_schedules:
            return

        logger.info("Backup scheduler: %d schedule(s) due for execution", len(due_schedules))

        for schedule in due_schedules:
            # Verificar se a instância existe e está RUNNING
            instance = (
                db.query(DatabaseInstance)
                .filter(
                    DatabaseInstance.id == schedule.instance_id,
                    DatabaseInstance.status == InstanceStatus.RUNNING,
                    DatabaseInstance.deleted_at.is_(None),
                    DatabaseInstance.connection_uri.isnot(None),
                )
                .first()
            )

            if not instance:
                logger.warning(
                    "Schedule %s: instance %s not found or not RUNNING — skipping",
                    schedule.id,
                    schedule.instance_id,
                )
                # Ainda avança o schedule para não ficar tentando repetidamente
                advance_schedule(db, schedule)
                continue

            try:
                if schedule.strategy == BackupStrategy.LOGICAL:
                    create_logical_backup(
                        db,
                        instance,
                        backup_type=BackupType.SCHEDULED,
                        retention_days=schedule.retention_days,
                    )
                elif schedule.strategy == BackupStrategy.PHYSICAL:
                    create_physical_backup(
                        db,
                        instance,
                        backup_type=BackupType.SCHEDULED,
                        retention_days=schedule.retention_days,
                    )

                # Aplicar retenção após cada backup agendado
                removed = apply_retention(db, instance.id)
                if removed > 0:
                    logger.info(
                        "Retention removed %d expired backups for instance %s",
                        removed,
                        instance.id,
                    )

            except Exception as exc:
                logger.exception(
                    "Backup schedule %s for instance %s failed: %s",
                    schedule.id,
                    instance.id,
                    exc,
                )
            finally:
                # Sempre avançar o schedule, mesmo em caso de falha,
                # para não tentar novamente no próximo ciclo de 60s
                advance_schedule(db, schedule)

    finally:
        db.close()


async def backup_scheduling_loop(stop_event: asyncio.Event) -> None:
    """
    Loop assíncrono que executa poll_schedules_once() a cada 60 segundos.

    Por que asyncio.to_thread()?
    poll_schedules_once() é síncrono (SQLAlchemy sync + subprocess). Rodar
    diretamente no event loop bloquearia todas as requests durante a execução.
    asyncio.to_thread() move a execução para uma thread pool, liberando o event loop.

    Por que asyncio.wait_for(stop_event.wait(), timeout=60)?
    Permite que o loop seja interrompido imediatamente quando a API faz shutdown,
    sem esperar o próximo ciclo de 60s. O TimeoutError é capturado e tratado como
    "continue o loop".
    """
    logger.info("Backup scheduling loop started (interval: 60s)")
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(poll_schedules_once)
        except Exception as exc:
            logger.exception("Unexpected error in backup scheduling loop: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
    logger.info("Backup scheduling loop stopped")
