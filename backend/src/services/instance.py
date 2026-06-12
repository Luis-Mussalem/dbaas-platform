import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse, urlunparse

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from src.core.encryption import decrypt_value, encrypt_value
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.schemas.instance import InstanceCreate, InstanceUpdate
from src.services.provisioning import get_provisioner

logger = logging.getLogger(__name__)

VALID_TRANSITIONS: dict[InstanceStatus, list[InstanceStatus]] = {
    InstanceStatus.PENDING: [InstanceStatus.PROVISIONING, InstanceStatus.FAILED],
    InstanceStatus.PROVISIONING: [InstanceStatus.RUNNING, InstanceStatus.FAILED],
    InstanceStatus.RUNNING: [InstanceStatus.STOPPED, InstanceStatus.DELETING, InstanceStatus.FAILED],
    InstanceStatus.STOPPED: [InstanceStatus.RUNNING, InstanceStatus.DELETING, InstanceStatus.FAILED],
    InstanceStatus.DELETING: [InstanceStatus.DELETED, InstanceStatus.FAILED],
    InstanceStatus.DELETED: [],
    InstanceStatus.FAILED: [InstanceStatus.PENDING, InstanceStatus.DELETED],
}


def _sync_connection_port(instance: DatabaseInstance, new_port: int) -> None:
    """
    Ressincronizar a porta e a connection_uri cifrada após um restart.

    Portas publicadas dinamicamente pelo Docker NÃO são preservadas entre
    stop/start — cada start pode receber uma porta nova. Sem isto, a
    connection_uri salva aponta para a porta velha e métricas/backups quebram.

    Decripta a URI, troca apenas a porta e re-cifra. O db_password permanece
    somente em memória durante esta função.
    """
    instance.port = new_port
    if instance.connection_uri:
        parsed = urlparse(decrypt_value(instance.connection_uri))
        netloc = f"{parsed.username}:{parsed.password}@{parsed.hostname}:{new_port}"
        new_uri = urlunparse(
            (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
        )
        instance.connection_uri = encrypt_value(new_uri)


def get_instance_by_id(db: Session, instance_id: uuid.UUID) -> Optional[DatabaseInstance]:
    return (
        db.query(DatabaseInstance)
        .filter(
            DatabaseInstance.id == instance_id,
            DatabaseInstance.deleted_at.is_(None),
        )
        .first()
    )


def list_instances(db: Session) -> list[DatabaseInstance]:
    return (
        db.query(DatabaseInstance)
        .filter(DatabaseInstance.deleted_at.is_(None))
        .order_by(DatabaseInstance.created_at.desc())
        .all()
    )


async def create_instance(db: Session, data: InstanceCreate) -> DatabaseInstance:
    """
    Criar um registro DatabaseInstance e provisionar um container PostgreSQL real.

    Fluxo completo:
    1. Criar registro no banco em status PENDING (visível ao operador imediatamente)
    2. Transicionar para PROVISIONING e commitar (poller sabe ignorar este estado)
    3. Rodar provisioner em thread pool — Docker API + psycopg são bloqueantes
       (asyncio.to_thread evita travar o event loop durante os ~10-30s de setup)
    4. Sucesso: popular host/port/db_name/db_user, cifrar connection_uri com
       Fernet e armazenar, marcar RUNNING
    5. Falha: marcar FAILED, levantar HTTP 503

    Por que asyncio.to_thread()?
    provisioner.create() faz polling de até 90s esperando o PostgreSQL iniciar.
    Se rodasse diretamente numa rota sync, bloquearia o único worker thread do
    uvicorn durante todo esse tempo, impedindo qualquer outro request de ser
    atendido. Com to_thread(), o trabalho vai para o thread pool do SO e o
    event loop continua livre.
    """
    instance = DatabaseInstance(
        name=data.name,
        engine_version=data.engine_version,
        cpu=data.cpu,
        memory_mb=data.memory_mb,
        storage_gb=data.storage_gb,
        region=data.region,
        environment=data.environment,
        notes=data.notes,
        status=InstanceStatus.PENDING,
    )
    db.add(instance)
    db.commit()
    db.refresh(instance)

    # Marcar como PROVISIONING antes de chamar o provisioner
    instance.status = InstanceStatus.PROVISIONING
    db.commit()

    provisioner = get_provisioner()
    try:
        result = await asyncio.to_thread(
            provisioner.create,
            instance.id,
            instance.engine_version,
            instance.memory_mb,
            instance.cpu,
        )
    except Exception as exc:
        instance.status = InstanceStatus.FAILED
        db.commit()
        # Loga o detalhe internamente; ao cliente vai só mensagem genérica —
        # str(exc) pode expor hostnames/portas/erros do Docker.
        logger.error("Provisioning failed for instance %s: %s", instance.id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Provisioning failed. See server logs for details.",
        ) from exc

    # Construir URI de conexão e cifrá-la com Fernet antes de persistir.
    # O db_password existe APENAS neste scope — após o commit ele é coletado
    # pelo GC e nunca mais acessível pelo código da aplicação.
    connection_uri = (
        f"postgresql://{result.db_user}:{result.db_password}"
        f"@{result.host}:{result.port}/{result.db_name}"
    )

    instance.host = result.host
    instance.port = result.port
    instance.db_name = result.db_name
    instance.db_user = result.db_user
    instance.connection_uri = encrypt_value(connection_uri)
    instance.status = InstanceStatus.RUNNING
    db.commit()
    db.refresh(instance)
    return instance


def update_instance(
    db: Session,
    instance: DatabaseInstance,
    data: InstanceUpdate,
) -> DatabaseInstance:
    if instance.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot update a deleted instance",
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(instance, field, value)

    db.commit()
    db.refresh(instance)
    return instance


async def transition_status(
    db: Session,
    instance: DatabaseInstance,
    new_status: InstanceStatus,
) -> DatabaseInstance:
    """
    Validar e aplicar uma transição de status, chamando o provisioner para
    operações de start/stop.

    O provisioner é invocado apenas para RUNNING ↔ STOPPED:
    - RUNNING → STOPPED: provisioner.stop() — para o container Docker graciosamente
    - STOPPED → RUNNING: provisioner.start() — reinicia o container existente

    Outras transições (→ FAILED, → DELETING) apenas atualizam o status no banco,
    sem interagir com o Docker. O DELETING→DELETED é exclusivo do soft_delete_instance.
    """
    allowed = VALID_TRANSITIONS.get(instance.status, [])
    if new_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot transition from '{instance.status.value}' "
                f"to '{new_status.value}'. "
                f"Allowed: {[s.value for s in allowed] or 'none'}"
            ),
        )

    provisioner = get_provisioner()

    if instance.status == InstanceStatus.RUNNING and new_status == InstanceStatus.STOPPED:
        try:
            await asyncio.to_thread(provisioner.stop, instance.id)
        except Exception as exc:
            instance.status = InstanceStatus.FAILED
            db.commit()
            logger.error("Failed to stop instance %s: %s", instance.id, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to stop the instance. See server logs for details.",
            ) from exc

    elif instance.status == InstanceStatus.STOPPED and new_status == InstanceStatus.RUNNING:
        try:
            new_port = await asyncio.to_thread(provisioner.start, instance.id)
        except Exception as exc:
            instance.status = InstanceStatus.FAILED
            db.commit()
            logger.error("Failed to start instance %s: %s", instance.id, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to start the instance. See server logs for details.",
            ) from exc
        # O Docker pode publicar uma porta diferente a cada start — ressincroniza
        # a porta e a connection_uri para métricas/backups continuarem válidos.
        _sync_connection_port(instance, new_port)

    instance.status = new_status
    db.commit()
    db.refresh(instance)
    return instance


async def soft_delete_instance(db: Session, instance: DatabaseInstance) -> DatabaseInstance:
    """
    Remover uma instância do uso ativo com cleanup completo do container.

    Fluxo:
    1. Validar pré-condições (não deletada, não rodando)
    2. Transicionar para DELETING e commitar (poller ignora este estado)
    3. Chamar provisioner.delete() — remove o container Docker (idempotente)
    4. Finalizar: marcar deleted_at + status DELETED

    O provisioner.delete() é idempotente: se o container não existir (ex: foi
    removido manualmente), ele não levanta erro — apenas continua.
    """
    if instance.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Instance is already deleted",
        )
    if instance.status == InstanceStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a running instance. Stop it first.",
        )

    instance.status = InstanceStatus.DELETING
    db.commit()

    provisioner = get_provisioner()
    try:
        await asyncio.to_thread(provisioner.delete, instance.id)
    except Exception as exc:
        instance.status = InstanceStatus.FAILED
        db.commit()
        logger.error("Failed to remove container for instance %s: %s", instance.id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to remove the instance container. See server logs for details.",
        ) from exc

    instance.deleted_at = datetime.now(timezone.utc)
    instance.status = InstanceStatus.DELETED
    db.commit()
    db.refresh(instance)
    return instance

