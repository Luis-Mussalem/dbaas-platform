import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from typing import Literal

from src.core.dependencies import (
    get_current_user,
    get_db,
    get_instance_if_running,
    get_instance_or_404,
)
from src.core.rate_limit import limiter
from src.models.database_instance import DatabaseInstance
from src.models.user import User
from src.schemas.metric import (
    ActiveConnectionsResponse,
    BloatResponse,
    ExplainRequest,
    ExplainResponse,
    HealthCheck,
    IndexStatsResponse,
    LocksResponse,
    MetricHistoryPoint,
    MetricHistoryResponse,
    MetricsSnapshot,
    SchemaResponse,
    SlowQueriesResponse,
)
from src.services import metrics as metrics_service

router = APIRouter(
    prefix="/instances",
    tags=["Monitoring"],
)


def _require_connected(
    instance_id: uuid.UUID,
    db: Session,
    current_user: User,
) -> DatabaseInstance:
    """
    Ensures the instance is RUNNING and has a connection_uri.

    All live monitoring endpoints need an active connection to the database.
    Historical endpoints (metrics snapshot) use get_instance_or_404 directly.
    current_user propagates multi-tenant scoping to all live endpoints.
    """
    instance = get_instance_if_running(instance_id, db, current_user)
    if not instance.connection_uri:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Instance has no connection URI — provisioning may not be complete",
        )
    return instance


@router.get(
    "/{instance_id}/metrics",
    response_model=MetricsSnapshot,
    summary="Return the most recent snapshot of scalar metrics",
)
def get_metrics(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MetricsSnapshot:
    """
    Returns the most recent value of each metric collected by the poller.

    Historical data — read from the platform's database, not the monitored one.
    Available even if the instance is STOPPED (shows the last reading).
    """
    # Scoped by company (404 for an instance from another company). Reuses the
    # bottleneck instead of repeating the query inline.
    get_instance_or_404(instance_id, db, current_user)

    current_metrics = metrics_service.get_latest_metrics(db, instance_id)
    return MetricsSnapshot(
        instance_id=instance_id,
        metrics=current_metrics,
    )


# Supported windows → minutes. Keeps the contract small and predictable for the UI.
_WINDOW_MINUTES = {"15m": 15, "1h": 60, "6h": 360, "24h": 1440}


@router.get(
    "/{instance_id}/metrics/history",
    response_model=MetricHistoryResponse,
    summary="Return a metric's time series for sparklines/charts",
)
def get_metrics_history(
    instance_id: uuid.UUID,
    metric: str = Query(..., min_length=1, max_length=100, description="metric_name collected by the poller"),
    window: Literal["15m", "1h", "6h", "24h"] = "1h",
    points: int = Query(
        120, ge=10, le=500,
        description="Resolution: the series is resampled into up to N buckets (average per bucket)",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MetricHistoryResponse:
    """
    Historical series of a single metric over the chosen window.

    Reads from the metrics table (platform database) — works even with the instance
    STOPPED, showing the history already collected. Returns an empty list if the metric
    hasn't been collected yet.

    The series is resampled into up to `points` buckets (average per bucket): the
    collection cadence varies (60s normally, 5s during the usage simulation) and without
    this the same chart would look smooth or jagged depending on the moment. A
    card sparkline needs fewer points than a full-page chart.
    """
    get_instance_or_404(instance_id, db, current_user)
    series = metrics_service.get_metric_history(
        db, instance_id, metric, _WINDOW_MINUTES[window], max_points=points
    )
    return MetricHistoryResponse(
        instance_id=instance_id,
        metric_name=metric,
        window=window,
        points=[MetricHistoryPoint(collected_at=ts, value=v) for ts, v in series],
    )


@router.get(
    "/{instance_id}/health",
    response_model=HealthCheck,
    summary="Check the instance's connectivity and responsiveness",
)
async def get_health(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HealthCheck:
    """
    Runs SELECT 1 on the monitored database and measures end-to-end response time.

    Live endpoint — connects to the instance's database at call time.
    """
    instance = _require_connected(instance_id, db, current_user)
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
    summary="Return queries with the highest total execution time",
)
async def get_slow_queries(
    instance_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SlowQueriesResponse:
    """
    Queries pg_stat_statements ordered by total_exec_time DESC.

    Requires pg_stat_statements to be installed. Instances provisioned after
    Step 4A already have the extension. Older instances return an empty list.
    """
    instance = _require_connected(instance_id, db, current_user)
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
    summary="Return index usage statistics",
)
async def get_indexes(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> IndexStatsResponse:
    """
    Queries pg_stat_user_indexes. Indexes with idx_scan=0 are candidates for DROP.
    """
    instance = _require_connected(instance_id, db, current_user)
    rows = await asyncio.to_thread(metrics_service.get_index_stats, instance)
    return IndexStatsResponse(
        instance_id=instance_id,
        indexes=rows,
    )


@router.get(
    "/{instance_id}/locks",
    response_model=LocksResponse,
    summary="Return active locks on tables",
)
async def get_locks(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LocksResponse:
    """
    Queries pg_locks filtered by locktype='relation'.
    has_blocked_queries=True indicates there are queries waiting on a lock.
    """
    instance = _require_connected(instance_id, db, current_user)
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
    summary="Return an estimate of bloat per table",
)
async def get_bloat(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BloatResponse:
    """
    Estimates the percentage of dead tuples per table via pg_stat_user_tables.
    dead_ratio > 20% indicates the need for VACUUM (PHASE 6).
    """
    instance = _require_connected(instance_id, db, current_user)
    rows = await asyncio.to_thread(metrics_service.get_bloat, instance)
    return BloatResponse(
        instance_id=instance_id,
        tables=rows,
    )


@router.get(
    "/{instance_id}/connections",
    response_model=ActiveConnectionsResponse,
    summary="List active connections (pg_stat_activity)",
)
async def get_connections(
    instance_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActiveConnectionsResponse:
    """
    Lists the backends connected to the instance's database (PID, user, state,
    wait, duration, and query). Live endpoint — requires the instance to be RUNNING.
    """
    instance = _require_connected(instance_id, db, current_user)
    rows = await asyncio.to_thread(
        metrics_service.get_active_connections, instance, limit
    )
    return ActiveConnectionsResponse(instance_id=instance_id, connections=rows)


@router.get(
    "/{instance_id}/schema",
    response_model=SchemaResponse,
    summary="Explore the database schema (tables per schema)",
)
async def get_schema(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SchemaResponse:
    """
    Returns user tables grouped by schema, with an estimated row count
    (pg_class.reltuples). Live endpoint — requires the instance to be RUNNING.
    """
    instance = _require_connected(instance_id, db, current_user)
    groups = await asyncio.to_thread(metrics_service.get_schema, instance)
    return SchemaResponse(instance_id=instance_id, schemas=groups)


@router.post(
    "/{instance_id}/explain",
    response_model=ExplainResponse,
    summary="Run EXPLAIN ANALYZE for a SELECT query",
)
@limiter.limit("30/minute")
async def explain_query(
    request: Request,  # noqa: ARG001 — required by slowapi's limiter decorator
    instance_id: uuid.UUID,
    body: ExplainRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExplainResponse:
    """
    Runs EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) on the given query.

    Restricted to SELECT: EXPLAIN ANALYZE actually executes the query,
    so DML would cause real effects on the client's data.

    Rate-limited for the same reason as the SQL console: ANALYZE means this runs
    the customer's query for real, and `statement_timeout` bounds one execution
    but not how many are requested per minute.
    """
    instance = _require_connected(instance_id, db, current_user)
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
