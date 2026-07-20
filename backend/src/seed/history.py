"""
Enriquecimento histórico da frota de demonstração.

O seed base (demo.py) cria empresas, usuários e instâncias — mas as telas de
Alertas, Backups, Manutenção e o KPI de uptime nascem vazias num clone limpo,
porque essas tabelas só se populam com o tempo (pollers/schedulers) ou com ação
manual. Este módulo preenche esse histórico de uma vez, de forma idempotente,
para o recrutador ver um produto "com quilometragem":

- **Métricas** — 24h de série sintética (a janela máxima dos gráficos é 24h),
  em TODAS as instâncias demo (containers reais inclusos: o poller ao vivo
  continua adicionando pontos por cima).
- **Uptime** — retroage `created_at` ~45 dias e semeia `instance_status_history`
  (RUNNING desde a criação, com um blip curto numa instância) para o KPI de
  30 dias exibir ~99.9% em vez de "—".
- **Alertas** — regras por instância + uma timeline de eventos resolvidos e
  poucos eventos abertos (para o dashboard mostrar alertas ativos reais).
- **Backups** — um schedule diário por prod + ~2 semanas de backups COMPLETED
  (tamanho crescente), 1 FAILED e 1 nas últimas 24h.
- **Manutenção** — um schedule semanal por prod + histórico de VACUUM/ANALYZE.
- **Audit log** — um fluxo de ações atribuídas aos usuários demo, para a
  atividade recente ter profundidade e o ator real (email@empresa) aparecer.

Tudo é dado mock plausível (nada sensível). Idempotente: cada instância é pulada
se já tiver regras de alerta, então religar o stack não duplica nada.
`clear()` no demo.py remove os recursos sem FK-cascade (backups, schedules e
audit logs demo).
"""
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from math import sin

from sqlalchemy.orm import Session

from src.models.alert import (
    AlertCondition,
    AlertEvent,
    AlertRule,
    AlertSeverity,
)
from src.models.audit_log import AuditLog
from src.models.backup import (
    Backup,
    BackupSchedule,
    BackupStatus,
    BackupStrategy,
    BackupType,
)
from src.models.company import Company
from src.models.database_instance import DatabaseInstance, Environment, InstanceStatus
from src.models.instance_status_history import InstanceStatusHistory
from src.models.maintenance import (
    MaintenanceSchedule,
    MaintenanceTask,
    TaskStatus,
    TaskType,
)
from src.models.metric import Metric
from src.models.user import User, UserRole

logger = logging.getLogger(__name__)

# Quanto tempo a frota "existe": retroagimos created_at para além da janela de
# 30 dias do uptime, para o KPI cobrir os 30 dias inteiros.
_FLEET_AGE_DAYS = 45

# Instâncias (por nome) que ficam com 1 alerta ABERTO — o resto só tem histórico
# resolvido. Mantém o contador de "alertas ativos" pequeno e crível.
_OPEN_ALERT_INSTANCES = {"neptune-payments-prod", "saturn-store-staging"}

_UNIT_BY_METRIC = {
    "connections_ratio": "%",
    "cache_hit_ratio": "%",
    "db_usage_percent": "%",
    "backup_age_hours": "h",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rng(instance: DatabaseInstance) -> random.Random:
    """RNG determinístico por instância — variedade estável entre reboots."""
    return random.Random(f"demo-history::{instance.name}")


def _alert_message(rule: AlertRule, current_value: float) -> str:
    """Mesmo formato que services.alert._build_message grava nos eventos reais."""
    unit = _UNIT_BY_METRIC.get(rule.metric_type, "")
    return (
        f"[{rule.severity.value.upper()}] {rule.name}: "
        f"current={current_value:.2f}{unit}, "
        f"threshold={rule.condition.value} {rule.threshold}{unit}"
    )


# --------------------------------------------------------------------------- #
# Métricas (24h @ 5min) — a janela máxima dos gráficos é 24h
# --------------------------------------------------------------------------- #
def _backfill_metrics(db: Session, instance: DatabaseInstance, idx: int) -> None:
    """
    Série de 24h (288 pontos, um a cada 5 min) para sparklines e gráficos.

    Soma de senoides → linha suave e orgânica. Cobre as métricas que a UI
    plota (connections_active, cache_hit_ratio, db_size_bytes) mais o teto de
    conexões. Não semeia xact_commit/p95: esses alimentam KPIs instantâneos de
    instâncias RUNNING e o poller ao vivo os preenche — as instâncias
    dados-apenas ficam STOPPED e não entram nesses KPIs de qualquer forma.
    """
    if db.query(Metric).filter(Metric.instance_id == instance.id).first():
        return  # já tem métricas — não duplica

    now = _now()
    capacity = (instance.storage_gb or 20) * 1024 ** 3
    base = 40 + idx * 30
    cache_base = 96 + idx * 0.7
    used = 0.35 + idx * 0.15
    n_points = 288
    rows: list[Metric] = []
    for k in range(n_points):
        ts = now - timedelta(minutes=(n_points - 1 - k) * 5)
        conns = max(0, base + 16 * sin(k / 30.0) + 7 * sin(k / 12.5) + 3 * sin(k / 5.5))
        cache = min(99.9, max(90.0, cache_base + 0.8 * sin(k / 22.0) + 0.4 * sin(k / 9.0)))
        size = used * capacity * (0.97 + 0.0001 * k)
        rows.append(Metric(instance_id=instance.id, metric_name="connections_active",
                           value=float(round(conns)), collected_at=ts))
        rows.append(Metric(instance_id=instance.id, metric_name="cache_hit_ratio",
                           value=round(cache, 2), collected_at=ts))
        rows.append(Metric(instance_id=instance.id, metric_name="db_size_bytes",
                           value=float(int(size)), collected_at=ts))
    rows.append(Metric(instance_id=instance.id, metric_name="connections_max",
                       value=100.0, collected_at=now))
    db.add_all(rows)
    db.commit()


# --------------------------------------------------------------------------- #
# Uptime — created_at retroagido + histórico de status
# --------------------------------------------------------------------------- #
def _backdate_status(db: Session, instance: DatabaseInstance, blip: bool) -> None:
    """
    Retroage created_at ~45 dias e grava o histórico de status para o uptime.

    RUNNING desde a criação. Se `blip`, insere um par STOPPED→RUNNING de ~25 min
    ~9 dias atrás — assim o uptime fica ~99.9x% (crível) em vez de 100% redondo.
    """
    now = _now()
    created = now - timedelta(days=_FLEET_AGE_DAYS)
    instance.created_at = created
    db.add(instance)

    rows = [InstanceStatusHistory(
        instance_id=instance.id, status=InstanceStatus.RUNNING, changed_at=created,
    )]
    if blip:
        down = now - timedelta(days=9, minutes=13)
        up = down + timedelta(minutes=25)
        rows.append(InstanceStatusHistory(
            instance_id=instance.id, status=InstanceStatus.STOPPED, changed_at=down))
        rows.append(InstanceStatusHistory(
            instance_id=instance.id, status=InstanceStatus.RUNNING, changed_at=up))
    db.add_all(rows)
    db.commit()


# --------------------------------------------------------------------------- #
# Alertas — regras + timeline de eventos
# --------------------------------------------------------------------------- #
def _seed_alerts(db: Session, instance: DatabaseInstance, is_prod: bool) -> None:
    rng = _rng(instance)
    now = _now()

    specs = [
        ("Cache hit ratio below target", "cache_hit_ratio", AlertCondition.LT, 95.0,
         AlertSeverity.WARNING),
        ("Connection pool saturation", "connections_ratio", AlertCondition.GT, 80.0,
         AlertSeverity.WARNING),
        ("Backup overdue", "backup_age_hours", AlertCondition.GT, 24.0,
         AlertSeverity.CRITICAL),
    ]
    if is_prod:
        specs.append(("Disk usage high", "db_usage_percent", AlertCondition.GT, 85.0,
                      AlertSeverity.WARNING))

    rules: dict[str, AlertRule] = {}
    for name, metric_type, cond, threshold, severity in specs:
        rule = AlertRule(
            instance_id=instance.id,
            name=name,
            metric_type=metric_type,
            condition=cond,
            threshold=threshold,
            severity=severity,
            is_active=True,
            created_at=now - timedelta(days=_FLEET_AGE_DAYS - 1),
        )
        db.add(rule)
        rules[metric_type] = rule
    db.commit()

    # Timeline de eventos RESOLVIDOS (o problema veio e passou). Alguns por
    # instância, espalhados nas últimas semanas — dão histórico à página.
    events: list[AlertEvent] = []
    n_resolved = rng.randint(2, 4)
    for _ in range(n_resolved):
        rule = rules[rng.choice(["cache_hit_ratio", "connections_ratio"])]
        days_ago = rng.uniform(1.5, 25.0)
        triggered = now - timedelta(days=days_ago)
        resolved = triggered + timedelta(minutes=rng.randint(6, 90))
        current = (rule.threshold - rng.uniform(0.5, 3.0)
                   if rule.condition == AlertCondition.LT
                   else rule.threshold + rng.uniform(2.0, 15.0))
        events.append(AlertEvent(
            rule_id=rule.id, instance_id=instance.id,
            triggered_at=triggered, resolved_at=resolved,
            current_value=round(current, 2), message=_alert_message(rule, current),
        ))

    # Evento ABERTO (resolved_at=NULL) só nas instâncias escolhidas — mantém o
    # contador de alertas ativos pequeno e realista.
    if instance.name in _OPEN_ALERT_INSTANCES:
        rule = rules["connections_ratio"] if is_prod else rules["cache_hit_ratio"]
        current = (rule.threshold + 9.4 if rule.condition == AlertCondition.GT
                   else rule.threshold - 1.8)
        events.append(AlertEvent(
            rule_id=rule.id, instance_id=instance.id,
            triggered_at=now - timedelta(minutes=rng.randint(12, 140)),
            resolved_at=None,
            current_value=round(current, 2), message=_alert_message(rule, current),
        ))

    db.add_all(events)
    db.commit()


# --------------------------------------------------------------------------- #
# Backups — schedule + histórico
# --------------------------------------------------------------------------- #
def _seed_backups(db: Session, instance: DatabaseInstance, is_prod: bool) -> None:
    rng = _rng(instance)
    now = _now()
    two_am = now.replace(hour=2, minute=0, second=0, microsecond=0)

    if is_prod:
        db.add(BackupSchedule(
            instance_id=instance.id,
            strategy=BackupStrategy.LOGICAL,
            cron_expression="0 2 * * *",
            retention_days=7,
            is_active=True,
            created_at=now - timedelta(days=_FLEET_AGE_DAYS - 1),
            last_run_at=two_am if two_am <= now else two_am - timedelta(days=1),
            next_run_at=two_am + timedelta(days=1),
        ))

    backups: list[Backup] = []
    # ~14 dias de backups diários agendados, COMPLETED, tamanho crescendo devagar.
    base_size = (55 + rng.randint(0, 40)) * 1024 ** 2  # ~55–95 MB
    for d in range(14, 0, -1):
        started = two_am - timedelta(days=d)
        if started > now:
            continue
        duration = rng.randint(40, 210)
        size = int(base_size * (1 + (14 - d) * 0.015) + rng.randint(-2, 2) * 1024 ** 2)
        backups.append(Backup(
            instance_id=instance.id,
            backup_type=BackupType.SCHEDULED,
            strategy=BackupStrategy.LOGICAL,
            status=BackupStatus.COMPLETED,
            file_path=f"/var/lib/dbaas/backups/{instance.id}/{started:%Y%m%dT%H%M%S}.dump",
            size_bytes=size,
            created_at=started,
            started_at=started,
            completed_at=started + timedelta(seconds=duration),
            expires_at=started + timedelta(days=7),
        ))

    # Um FAILED no meio do caminho, para o histórico não parecer "bom demais".
    failed_at = two_am - timedelta(days=6)
    backups.append(Backup(
        instance_id=instance.id,
        backup_type=BackupType.SCHEDULED,
        strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.FAILED,
        created_at=failed_at,
        started_at=failed_at,
        completed_at=failed_at + timedelta(seconds=8),
        error_message="pg_dump: connection to server failed: timeout expired",
    ))

    # Um backup manual FÍSICO recente (variedade de strategy/type na UI).
    if is_prod:
        man_at = now - timedelta(hours=rng.randint(30, 50))
        backups.append(Backup(
            instance_id=instance.id,
            backup_type=BackupType.MANUAL,
            strategy=BackupStrategy.PHYSICAL,
            status=BackupStatus.COMPLETED,
            file_path=f"/var/lib/dbaas/backups/{instance.id}/basebackup-{man_at:%Y%m%d}",
            size_bytes=int(base_size * 2.4),
            created_at=man_at,
            started_at=man_at,
            completed_at=man_at + timedelta(minutes=4),
            expires_at=man_at + timedelta(days=30),
        ))

    # Garante ≥1 backup nas últimas 24h (para o KPI "backups nas últimas 24h").
    recent_at = now - timedelta(hours=rng.randint(2, 9))
    backups.append(Backup(
        instance_id=instance.id,
        backup_type=BackupType.SCHEDULED,
        strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.COMPLETED,
        file_path=f"/var/lib/dbaas/backups/{instance.id}/{recent_at:%Y%m%dT%H%M%S}.dump",
        size_bytes=int(base_size * 1.22),
        created_at=recent_at,
        started_at=recent_at,
        completed_at=recent_at + timedelta(seconds=rng.randint(40, 180)),
        expires_at=recent_at + timedelta(days=7),
    ))

    db.add_all(backups)
    db.commit()


# --------------------------------------------------------------------------- #
# Manutenção — schedule + histórico
# --------------------------------------------------------------------------- #
def _seed_maintenance(
    db: Session, instance: DatabaseInstance, is_prod: bool, table: str | None
) -> None:
    rng = _rng(instance)
    now = _now()

    if is_prod:
        # Domingo 03:00 → próxima ocorrência.
        days_to_sunday = (6 - now.weekday()) % 7 or 7
        next_run = (now + timedelta(days=days_to_sunday)).replace(
            hour=3, minute=0, second=0, microsecond=0)
        db.add(MaintenanceSchedule(
            instance_id=instance.id,
            task_type=TaskType.VACUUM,
            cron_expression="0 3 * * 0",
            is_active=True,
            created_at=now - timedelta(days=_FLEET_AGE_DAYS - 1),
            next_run_at=next_run,
        ))

    tasks: list[MaintenanceTask] = []
    plan = [
        (TaskType.VACUUM, None, "VACUUM completed: {n} tables processed, {mb} MB reclaimed"),
        (TaskType.ANALYZE, table, "ANALYZE completed on {tbl}: planner statistics refreshed"),
        (TaskType.REINDEX, table, "REINDEX completed: {n} indexes rebuilt"),
        (TaskType.VACUUM, None, "VACUUM completed: {n} tables processed, {mb} MB reclaimed"),
    ]
    for i, (task_type, target, tmpl) in enumerate(plan):
        scheduled = now - timedelta(days=rng.uniform(2.0, 21.0), hours=rng.randint(0, 12))
        started = scheduled + timedelta(seconds=rng.randint(1, 30))
        summary = tmpl.format(
            n=rng.randint(3, 18), mb=round(rng.uniform(0.4, 12.0), 1), tbl=target or "public")
        tasks.append(MaintenanceTask(
            instance_id=instance.id,
            task_type=task_type,
            status=TaskStatus.COMPLETED,
            target_table=target,
            scheduled_at=scheduled,
            started_at=started,
            completed_at=started + timedelta(seconds=rng.randint(2, 240)),
            result_summary=summary,
        ))
    db.add_all(tasks)
    db.commit()


# --------------------------------------------------------------------------- #
# Audit log — fluxo de ações dos usuários demo
# --------------------------------------------------------------------------- #
def _seed_audit(
    db: Session,
    company: Company,
    admin: User,
    members: list[User],
    instances: list[DatabaseInstance],
) -> None:
    now = _now()
    entries: list[AuditLog] = []

    def add(user, action, resource_type, resource_id, path, method, days_ago, hours=0):
        ts = now - timedelta(days=days_ago, hours=hours)
        entries.append(AuditLog(
            user_id=user.id if user else None,
            company_id=company.id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            details={"method": method, "path": path, "status": 200},
            ip_address="203.0.113.%d" % (7 + (hash(user.email) % 40) if user else 1),
            timestamp=ts,
        ))

    # Criação da frota (admin), no começo da vida da empresa.
    for inst in instances:
        add(admin, "instance_created", "instance", inst.id,
            "/api/v1/instances", "POST", days_ago=_FLEET_AGE_DAYS - 1)
        add(admin, "schedule_created", "backup_schedule", inst.id,
            f"/api/v1/instances/{inst.id}/schedules", "POST", days_ago=_FLEET_AGE_DAYS - 1)

    # Fluxo recente e crível: logins, backups manuais, manutenção, um restore.
    pool = [admin, *members]
    for d in range(12, 0, -1):
        user = pool[d % len(pool)]
        add(user, "login", "auth", None, "/api/v1/auth/login", "POST",
            days_ago=d, hours=(d * 2) % 12)
    if instances:
        prod = instances[0]
        add(members[0], "backup_created", "backup", prod.id,
            f"/api/v1/instances/{prod.id}/backups", "POST", days_ago=2, hours=6)
        add(admin, "maintenance_run", "maintenance", prod.id,
            f"/api/v1/instances/{prod.id}/maintenance/run", "POST", days_ago=1, hours=3)
        add(members[1 % len(members)], "restore_initiated", "backup", prod.id,
            f"/api/v1/backups/{prod.id}/restore", "POST", days_ago=4, hours=1)
        add(admin, "instance_status_changed", "instance", prod.id,
            f"/api/v1/instances/{prod.id}/status", "PATCH", days_ago=9)

    db.add_all(entries)
    db.commit()


# --------------------------------------------------------------------------- #
# Orquestração
# --------------------------------------------------------------------------- #
def enrich_fleet(db: Session) -> None:
    """
    Semeia histórico (métricas, uptime, alertas, backups, manutenção, audit) para
    a frota demo. Idempotente: instância com regras de alerta já existentes é
    pulada; audit por empresa só é semeado se a empresa ainda não tem logs.
    """
    from src.seed.demo import COMPANIES, DEMO_MARKER  # lazy: evita import circular

    instances = (
        db.query(DatabaseInstance)
        .filter(DatabaseInstance.notes == DEMO_MARKER,
                DatabaseInstance.deleted_at.is_(None))
        .order_by(DatabaseInstance.name.asc())
        .all()
    )
    if not instances:
        return

    # Tabela alvo (para ANALYZE/REINDEX) por empresa, via config do demo.
    table_by_company: dict[uuid.UUID, str] = {}
    for company_name, cfg in COMPANIES.items():
        comp = db.query(Company).filter(Company.name == company_name).first()
        if comp is not None:
            table_by_company[comp.id] = cfg["table"]

    for idx, inst in enumerate(instances):
        if db.query(AlertRule).filter(AlertRule.instance_id == inst.id).first():
            continue  # já enriquecida
        is_prod = inst.environment == Environment.PRODUCTION
        blip = inst.name in _OPEN_ALERT_INSTANCES  # reaproveita: quem tem alerta aberto teve um blip
        logger.info("Seed demo: enriquecendo histórico de %s ...", inst.name)
        _backfill_metrics(db, inst, idx)
        _backdate_status(db, inst, blip=blip)
        _seed_alerts(db, inst, is_prod)
        _seed_backups(db, inst, is_prod)
        _seed_maintenance(db, inst, is_prod, table_by_company.get(inst.company_id))

    # Audit por empresa (uma vez, se ainda vazia).
    by_company: dict[uuid.UUID, list[DatabaseInstance]] = {}
    for inst in instances:
        if inst.company_id is not None:
            by_company.setdefault(inst.company_id, []).append(inst)
    for company_id, insts in by_company.items():
        if db.query(AuditLog).filter(AuditLog.company_id == company_id).first():
            continue
        company = db.query(Company).filter(Company.id == company_id).first()
        if company is None:
            continue
        users = (
            db.query(User)
            .filter(User.company_id == company_id)
            .order_by(User.email.asc())
            .all()
        )
        admin = next((u for u in users if u.role == UserRole.ADMIN), None)
        members = [u for u in users if u.role == UserRole.MEMBER]
        if admin and members:
            _seed_audit(db, company, admin, members, sorted(insts, key=lambda i: i.name))

    logger.info("Seed demo: histórico da frota concluído.")
