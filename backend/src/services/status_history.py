import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.instance_status_history import InstanceStatusHistory

# Janela de referência para o cálculo de uptime.
_UPTIME_WINDOW = timedelta(days=30)


def record_status_change(
    db: Session, instance: DatabaseInstance, new_status: InstanceStatus
) -> None:
    """
    Aplicar a mudança de status na instância E registrar a transição no histórico.

    NÃO faz commit de propósito: todo call site já commita logo em seguida, então
    a linha de histórico entra na mesma transação da mudança de status — se der
    rollback, as duas somem juntas (atomicidade).

    Só deve ser chamada quando o status realmente muda; os call sites já garantem
    isso (transições válidas ou guardas `if status != X`), então não filtramos
    aqui — evita esconder um no-op que sinalizaria um bug no chamador.
    """
    instance.status = new_status
    db.add(InstanceStatusHistory(instance_id=instance.id, status=new_status))


def _uptime_from_rows(
    rows: list[InstanceStatusHistory],
    created_at: datetime,
    now: datetime,
) -> float | None:
    """
    Calcular a % de tempo em RUNNING na janela [max(now - 30d, created_at), now].

    `rows`: histórico de UMA instância ordenado por changed_at ASC. Vazio → None
    (instância anterior ao rastreamento — melhor exibir "—" que fabricar 0/100%).

    O status vigente no início da janela é o do último registro com
    changed_at <= window_start (carry-in), permitindo janelas que começam no meio
    de um período RUNNING para instâncias com mais de 30 dias.
    """
    if not rows:
        return None

    window_start = max(now - _UPTIME_WINDOW, created_at)
    total = (now - window_start).total_seconds()
    if total <= 0:
        return None

    # Carry-in: status ativo em window_start.
    current = rows[0].status
    for row in rows:
        if row.changed_at <= window_start:
            current = row.status
        else:
            break

    running_seconds = 0.0
    cursor = window_start
    for row in rows:
        if row.changed_at <= window_start:
            continue
        if row.changed_at >= now:
            break
        if current == InstanceStatus.RUNNING:
            running_seconds += (row.changed_at - cursor).total_seconds()
        cursor = row.changed_at
        current = row.status

    # Segmento final: do último boundary até agora.
    if current == InstanceStatus.RUNNING:
        running_seconds += (now - cursor).total_seconds()

    return round(running_seconds / total * 100, 2)


def get_instance_uptime_pct(
    db: Session, instance: DatabaseInstance
) -> float | None:
    """Uptime (% em RUNNING nos últimos 30 dias) de uma única instância."""
    rows = (
        db.query(InstanceStatusHistory)
        .filter(InstanceStatusHistory.instance_id == instance.id)
        .order_by(InstanceStatusHistory.changed_at.asc())
        .all()
    )
    return _uptime_from_rows(rows, instance.created_at, datetime.now(timezone.utc))


def get_fleet_uptime_pct(
    db: Session, company_id: uuid.UUID | None = None
) -> float | None:
    """
    Uptime médio da frota: média simples do uptime por instância (não deletada),
    escopada por empresa. None se nenhuma instância tem histórico ainda.

    Uma única query traz todos os registros das instâncias no escopo; o
    agrupamento por instância e o cálculo por instância acontecem em Python
    (escala de portfólio — poucas instâncias; sem necessidade de view/cache).
    """
    inst_q = db.query(DatabaseInstance).filter(DatabaseInstance.deleted_at.is_(None))
    if company_id is not None:
        inst_q = inst_q.filter(DatabaseInstance.company_id == company_id)
    instances = inst_q.all()
    if not instances:
        return None

    instance_ids = [inst.id for inst in instances]
    rows = (
        db.query(InstanceStatusHistory)
        .filter(InstanceStatusHistory.instance_id.in_(instance_ids))
        .order_by(InstanceStatusHistory.changed_at.asc())
        .all()
    )

    by_instance: dict[uuid.UUID, list[InstanceStatusHistory]] = {}
    for row in rows:
        by_instance.setdefault(row.instance_id, []).append(row)

    now = datetime.now(timezone.utc)
    pcts = [
        pct
        for inst in instances
        if (
            pct := _uptime_from_rows(by_instance.get(inst.id, []), inst.created_at, now)
        )
        is not None
    ]
    if not pcts:
        return None
    return round(sum(pcts) / len(pcts), 2)
