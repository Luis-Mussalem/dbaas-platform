import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AlertMetricType(str, Enum):
    """
    Metric types supported by the alert evaluator.

    connections_ratio   — % of max connections in use (connections_active / connections_max * 100)
    cache_hit_ratio     — % of reads served by the cache (target: > 95%)
    db_usage_percent    — % of allocated storage consumed by the database (db_size_bytes / storage_gb)
    long_query_seconds  — duration in seconds of the oldest active query (via pg_stat_activity)
    backup_age_hours    — hours since the last COMPLETED backup (999h if there was never a backup)
    """

    CONNECTIONS_RATIO  = "connections_ratio"
    CACHE_HIT_RATIO    = "cache_hit_ratio"
    DB_USAGE_PERCENT   = "db_usage_percent"
    LONG_QUERY_SECONDS = "long_query_seconds"
    BACKUP_AGE_HOURS   = "backup_age_hours"


class AlertCondition(str, Enum):
    GT  = "gt"
    GTE = "gte"
    LT  = "lt"
    LTE = "lte"
    EQ  = "eq"


class AlertSeverity(str, Enum):
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"


class AlertRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    metric_type: AlertMetricType
    condition: AlertCondition
    threshold: float
    severity: AlertSeverity = AlertSeverity.WARNING
    is_active: bool = True


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    condition: Optional[AlertCondition] = None
    threshold: Optional[float] = None
    severity: Optional[AlertSeverity] = None
    is_active: Optional[bool] = None


class AlertRuleRead(BaseModel):
    id: uuid.UUID
    instance_id: uuid.UUID
    name: str
    metric_type: str
    condition: str
    threshold: float
    severity: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AlertEventRead(BaseModel):
    id: uuid.UUID
    rule_id: uuid.UUID
    instance_id: uuid.UUID
    triggered_at: datetime
    resolved_at: Optional[datetime]
    current_value: float
    message: str

    model_config = {"from_attributes": True}
