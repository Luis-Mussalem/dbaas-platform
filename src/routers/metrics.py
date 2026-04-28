import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.core.dependencies import get_current_user, get_db
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.user import User
from src.schemas.metric import (
    BloatResponse,
    ExplainRequest,
    ExplainResponse,
    HealthCheck,
    IndexStatsResponse,
    LocksResponse,
    MetricsSnapshot,
    SlowQueriesResponse,
)
from src.services import metrics as metrics_service

router = APIRouter(
    prefix="/instances",
    tags=["monitoring"],
)


def _require_running(
    instance_id: uuid.UUID,
    db: Session,
) -> DatabaseInstance:
    """
    Buscar instância pelo ID e garantir que está RUNNING.

    Helper compartilhado por todos os endpoints de monitoramento live.
    Endpoints de dados históricos (metrics snapshot) não precisam da restrição
    de status — apenas de que a instância existe e não foi deletada.
    """
    instance = (
        db.query(DatabaseInstance)
        .filter(
            DatabaseInstance.id == instance_id,
            DatabaseInstance.deleted_at.is_(None),
        )
        .first()
    )
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instance not found",
        )
    if instance.status != InstanceStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Instance is not RUNNING (current status: {instance.status.value})",
        )
    if not instance.connection_uri:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Instance has no connection URI — provisioning may not be complete",
        )
    return instance


@router.get(
    "/{instance_id}/metrics",
    response_model=MetricsSnapshot,
    summary="Retornar o snapshot mais recente de métricas escalares",
)
def get_metrics(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> MetricsSnapshot:
    """
    Retorna os valores mais recentes de cada métrica coletada pelo poller.

    Dados históricos — lidos do banco da plataforma, não do banco monitorado.
    Disponível mesmo se a instância estiver STOPPED (exibe última leitura).
    """
    instance = (
        db.query(DatabaseInstance)
        .filter(
            DatabaseInstance.id == instance_id,
            DatabaseInstance.deleted_at.is_(None),
        )
        .first()
    )
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instance not found",
        )

    current_metrics = metrics_service.get_latest_metrics(db, instance_id)
    return MetricsSnapshot(
        instance_id=instance_id,
        metrics=current_metrics,
    )


@router.get(
    "/{instance_id}/health",
    response_model=HealthCheck,
    summary="Verificar conectividade e responsividade da instância",
)
async def get_health(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> HealthCheck:
    """
    Executa SELECT 1 no banco monitorado e mede response time end-to-end.

    Endpoint live — conecta ao banco da instância no momento da chamada.
    """
    instance = _require_running(instance_id, db)
    result = await asyncio.to_thread(metrics_service.check_health, instance)
    return HealthCheck(
        instance_id=instance_id,
        status=result["status"],
        response_time_ms=result["response_time_ms"],
        checked_at=result["checked_at"],
    )


@router.get(
    "/{instance_id}/slow-queries",
    response_model=SlowQueriesResponse,
    summary="Retornar queries com maior tempo total de execução",
)
async def get_slow_queries(
    instance_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SlowQueriesResponse:
    """
    Consulta pg_stat_statements ordenado por total_exec_time DESC.

    Requer pg_stat_statements instalado. Instâncias provisionadas após
    o Passo 4A já têm a extensão. Instâncias antigas retornam lista vazia.
    """
    instance = _require_running(instance_id, db)
    rows = await asyncio.to_thread(
        metrics_service.get_slow_queries, instance, limit
    )
    return SlowQueriesResponse(
        instance_id=instance_id,
        queries=rows,
    )


@router.get(
    "/{instance_id}/indexes",
    response_model=IndexStatsResponse,
    summary="Retornar estatísticas de uso de índices",
)
async def get_indexes(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> IndexStatsResponse:
    """
    Consulta pg_stat_user_indexes. Índices com idx_scan=0 são candidatos a DROP.
    """
    instance = _require_running(instance_id, db)
    rows = await asyncio.to_thread(metrics_service.get_index_stats, instance)
    return IndexStatsResponse(
        instance_id=instance_id,
        indexes=rows,
    )


@router.get(
    "/{instance_id}/locks",
    response_model=LocksResponse,
    summary="Retornar locks ativos em tabelas",
)
async def get_locks(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> LocksResponse:
    """
    Consulta pg_locks filtrado por locktype='relation'.
    has_blocked_queries=True indica que há queries aguardando lock.
    """
    instance = _require_running(instance_id, db)
    rows = await asyncio.to_thread(metrics_service.get_locks, instance)
    has_blocked = any(not row.get("granted", True) for row in rows)
    return LocksResponse(
        instance_id=instance_id,
        locks=rows,
        has_blocked_queries=has_blocked,
    )


@router.get(
    "/{instance_id}/bloat",
    response_model=BloatResponse,
    summary="Retornar estimativa de bloat por tabela",
)
async def get_bloat(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> BloatResponse:
    """
    Estima percentual de tuplas mortas por tabela via pg_stat_user_tables.
    dead_ratio > 20% indica necessidade de VACUUM (FASE 6).
    """
    instance = _require_running(instance_id, db)
    rows = await asyncio.to_thread(metrics_service.get_bloat, instance)
    return BloatResponse(
        instance_id=instance_id,
        tables=rows,
    )


@router.post(
    "/{instance_id}/explain",
    response_model=ExplainResponse,
    summary="Executar EXPLAIN ANALYZE para uma query SELECT",
)
async def explain_query(
    instance_id: uuid.UUID,
    body: ExplainRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ExplainResponse:
    """
    Executa EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) na query fornecida.

    Restrito a SELECT: EXPLAIN ANALYZE executa a query de verdade,
    portanto DML causaria efeitos reais nos dados do cliente.
    """
    instance = _require_running(instance_id, db)
    try:
        plan = await asyncio.to_thread(
            metrics_service.get_explain, instance, body.query
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return ExplainResponse(
        instance_id=instance_id,
        plan=plan,
    )
