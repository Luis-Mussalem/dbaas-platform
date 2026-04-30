import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MetricsSnapshot(BaseModel):
    instance_id: uuid.UUID
    metrics: dict[str, float]
    collected_at: datetime | None = None


class HealthCheck(BaseModel):
    instance_id: uuid.UUID
    status: Literal["healthy", "unhealthy"]
    response_time_ms: float
    checked_at: datetime


class SlowQuery(BaseModel):
    query: str
    calls: int
    total_exec_time_ms: float
    mean_exec_time_ms: float
    rows: int
    cache_hit_ratio: float


class SlowQueriesResponse(BaseModel):
    instance_id: uuid.UUID
    queries: list[SlowQuery]


class IndexStat(BaseModel):
    schema_name: str
    table: str
    index: str
    scans: int
    tup_read: int
    tup_fetch: int
    size_bytes: int
    unused: bool


class IndexStatsResponse(BaseModel):
    instance_id: uuid.UUID
    indexes: list[IndexStat]


class LockInfo(BaseModel):
    pid: int
    table: str | None
    mode: str
    granted: bool
    locktype: str


class LocksResponse(BaseModel):
    instance_id: uuid.UUID
    locks: list[LockInfo]
    has_blocked_queries: bool


class TableBloat(BaseModel):
    schema_name: str
    table: str
    live_rows: int
    dead_rows: int
    dead_ratio: float
    total_bytes: int


class BloatResponse(BaseModel):
    instance_id: uuid.UUID
    tables: list[TableBloat]


class ExplainRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=8000)


class ExplainResponse(BaseModel):
    instance_id: uuid.UUID
    plan: list
