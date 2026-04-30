import asyncio
import logging
from datetime import datetime, timezone

from src.core.database import SessionLocal
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.maintenance import MaintenanceSchedule, TaskType
from src.schemas.maintenance import MaintenanceTaskCreate

logger = logging.getLogger(__name__)

# Intervalo em segundos entre cada ciclo do agendador
_SCHEDULER_INTERVAL_SECONDS = 60

# VACUUM_FULL não pode ser agendado automaticamente:
# requer lock exclusivo na tabela — bloquearia leitura e escrita.
# Só deve ser executado manualmente via POST /maintenance/run com
# janela de manutenção planejada e target_table explícito.
_UNSCHEDULABLE = {TaskType.VACUUM_FULL}


def poll_schedules_once() -> None:
    """
    Verificar quais MaintenanceSchedules devem ser executados agora.

    Estratégia de despacho:
    1. Buscar todos os schedules ativos cuja next_run_at <= agora
    2. Para cada schedule: avançar next_run_at ANTES de executar
       (evita re-despacho se a execução demorar mais que _SCHEDULER_INTERVAL_SECONDS)
    3. Verificar se a instância está RUNNING (skip se STOPPED/FAILED/DELETED)
    4. Executar a tarefa (bloqueante — roda em thread via asyncio.to_thread)

    Por que avançar next_run_at antes de executar?
    Se avançarmos depois, e a tarefa demorar 2 minutos (REINDEX em tabela grande),
    o próximo ciclo do poller (60s) encontraria o mesmo schedule com next_run_at
    ainda no passado e despacharia novamente — duplicando a execução.
    Avançar antes garante que schedules concorrentes nunca duplicam.

    Por que checar InstanceStatus.RUNNING?
    VACUUM/REINDEX em container parado resultaria em ConnectionError e task FAILED.
    Mais importante: se a instância está STOPPED, não faz sentido manutenção —
    simplesmente pulamos e o schedule continua agendado para o próximo horário.

    Por que síncrono?
    Esta função é chamada via asyncio.to_thread() — pode fazer operações
    bloqueantes (SQL + psycopg) sem travar o event loop dos requests HTTP.
    """
    from src.services.maintenance import _TASK_RUNNERS, advance_schedule, run_task

    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        due_schedules = (
            db.query(MaintenanceSchedule)
            .join(
                DatabaseInstance,
                MaintenanceSchedule.instance_id == DatabaseInstance.id,
            )
            .filter(
                MaintenanceSchedule.is_active.is_(True),
                MaintenanceSchedule.next_run_at <= now,
                MaintenanceSchedule.task_type.notin_(list(_UNSCHEDULABLE)),
                DatabaseInstance.status == InstanceStatus.RUNNING,
                DatabaseInstance.deleted_at.is_(None),
            )
            .all()
        )

        for schedule in due_schedules:
            # Avançar next_run_at ANTES de executar
            advance_schedule(db, schedule)

            instance = (
                db.query(DatabaseInstance)
                .filter(DatabaseInstance.id == schedule.instance_id)
                .first()
            )
            if instance is None:
                logger.warning(
                    "Schedule %s sem instância correspondente — pulando",
                    schedule.id,
                )
                continue

            task_data = MaintenanceTaskCreate(
                task_type=schedule.task_type,
                target_table=None,  # schedules automáticos nunca têm target_table
            )

            try:
                task = run_task(db, instance, task_data)
                logger.info(
                    "Manutenção agendada executada: schedule=%s instance=%s "
                    "task_type=%s task_id=%s status=%s",
                    schedule.id,
                    instance.id,
                    schedule.task_type.value,
                    task.id,
                    task.status.value,
                )
            except Exception as exc:
                logger.error(
                    "Erro ao executar manutenção agendada: schedule=%s instance=%s "
                    "task_type=%s erro=%s",
                    schedule.id,
                    instance.id,
                    schedule.task_type.value,
                    exc,
                )

    except Exception as exc:
        logger.error("Erro no ciclo do maintenance scheduler: %s", exc)
    finally:
        db.close()


async def maintenance_scheduling_loop(stop_event: asyncio.Event) -> None:
    """
    Loop assíncrono do agendador de manutenção.

    Usa o mesmo padrão dos outros pollers (status_poller, metrics_poller,
    backup_scheduler): asyncio.to_thread() para não bloquear o event loop,
    asyncio.wait_for() para timeout de segurança.

    O timeout (180s) é maior que _SCHEDULER_INTERVAL_SECONDS (60s) para dar
    margem a REINDEX em tabelas grandes, mas evitar que um schedule travado
    bloqueie todos os subsequentes indefinidamente.

    O stop_event vem do lifespan do FastAPI — é setado no shutdown para
    encerrar o loop graciosamente.
    """
    logger.info("Maintenance scheduling loop iniciado")
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(
                asyncio.to_thread(poll_schedules_once),
                timeout=180.0,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Ciclo do maintenance scheduler excedeu 180s de timeout"
            )
        except Exception as exc:
            logger.error("Exceção inesperada no maintenance scheduling loop: %s", exc)

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=_SCHEDULER_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            pass

    logger.info("Maintenance scheduling loop encerrado")
