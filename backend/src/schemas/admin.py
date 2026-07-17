import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditLogRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    user_email: str | None = None
    company_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    details: dict[str, Any] | None
    ip_address: str | None
    timestamp: datetime

    model_config = {"from_attributes": True}


class DashboardResponse(BaseModel):
    total_instances: int
    instances_by_status: dict[str, int]
    active_alerts: int
    backups_last_24h: int
    failed_backups_last_24h: int
    pending_maintenance_tasks: int
    # KPIs de performance da frota (derivados de dados reais; None quando ainda
    # não há amostras suficientes — o frontend exibe "—", nunca um zero falso).
    queries_per_second: float
    p95_latency_ms: float | None = None
    fleet_uptime_pct: float | None = None
