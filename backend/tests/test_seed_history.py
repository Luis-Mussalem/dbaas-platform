"""
Testes do backfill histórico da frota demo (`src/seed/history.py`).

O foco é a guarda de idempotência, que é onde a coisa quebrou de verdade: a
versão anterior pulava o backfill se existisse QUALQUER métrica, e como o
poller ao vivo grava uma linha por minuto, bastava um intervalo entre o reset e
o clique em "Simular uso" para os gráficos de 24h nunca serem semeados.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.models.alert import AlertRule
from src.models.backup import Backup
from src.models.database_instance import DatabaseInstance, Environment, InstanceStatus
from src.models.metric import Metric
from src.seed import history

DEMO_MARKER = "__demo_fleet__"


@pytest.fixture
def demo_instance(db):
    inst = DatabaseInstance(
        name="demo-prod",
        status=InstanceStatus.RUNNING,
        environment=Environment.PRODUCTION,
        notes=DEMO_MARKER,
        storage_gb=1,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _series(db, instance, metric_name="connections_active") -> list[Metric]:
    return (
        db.query(Metric)
        .filter(Metric.instance_id == instance.id, Metric.metric_name == metric_name)
        .order_by(Metric.collected_at.asc())
        .all()
    )


def _add_live_sample(db, instance, name, value, minutes_ago=0):
    db.add(Metric(
        instance_id=instance.id,
        metric_name=name,
        value=value,
        collected_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    ))
    db.commit()


def test_backfill_seeds_the_window(db, demo_instance):
    history._backfill_metrics(db, demo_instance, idx=0)

    points = _series(db, demo_instance)
    span = points[-1].collected_at - points[0].collected_at
    assert len(points) > 200
    assert span > timedelta(hours=23)


def test_backfill_runs_even_when_the_live_poller_already_wrote(db, demo_instance):
    """
    REGRESSÃO: alguns minutos de coleta ao vivo não podem suprimir o backfill —
    era exatamente isso que deixava os gráficos com poucos minutos de dados
    depois de parar e simular de novo.
    """
    for minutes in (4, 3, 2, 1, 0):
        _add_live_sample(db, demo_instance, "connections_active", 7.0, minutes)

    history._backfill_metrics(db, demo_instance, idx=0)

    points = _series(db, demo_instance)
    assert points[0].collected_at < datetime.now(timezone.utc) - timedelta(hours=23)


def test_backfill_skips_when_the_window_is_already_covered(db, demo_instance):
    """Com 24h de medição real, o sintético é desnecessário — e não deve entrar."""
    _add_live_sample(db, demo_instance, "connections_active", 7.0, minutes_ago=60 * 24)
    before = len(_series(db, demo_instance))

    history._backfill_metrics(db, demo_instance, idx=0)

    assert len(_series(db, demo_instance)) == before


def test_seeded_series_stops_where_the_measured_one_starts(db, demo_instance):
    """Sem sobreposição: dois pontos concorrentes no mesmo instante viram ruído."""
    _add_live_sample(db, demo_instance, "connections_active", 7.0, minutes_ago=10)

    history._backfill_metrics(db, demo_instance, idx=0)

    seeded = [p for p in _series(db, demo_instance) if p.value != 7.0]
    junction = datetime.now(timezone.utc) - timedelta(minutes=10)
    assert max(p.collected_at for p in seeded) <= junction


def test_size_series_is_anchored_to_the_measured_size(db, demo_instance):
    """
    O tamanho semeado converge para o que a instância REALMENTE reporta.

    Antes ele era uma fração arbitrária da capacidade contratada: com o plano de
    1 GB isso desenhava um degrau na emenda e uma barra de storage acima de 100%.
    """
    measured = 264.0 * 1024 ** 2
    _add_live_sample(db, demo_instance, "db_size_bytes", measured, minutes_ago=10)

    history._backfill_metrics(db, demo_instance, idx=0)

    seeded = [p.value for p in _series(db, demo_instance, "db_size_bytes")
              if p.value != measured]
    # Termina logo abaixo do medido (o banco cresceu ao longo do dia) e nunca
    # ultrapassa a capacidade do plano.
    assert 0.95 * measured < max(seeded) <= measured
    assert max(seeded) < demo_instance.storage_gb * 1024 ** 3


def test_enrich_fleet_still_seeds_backups_when_only_a_rule_exists(db, demo_instance):
    """
    REGRESSÃO: a fase ALERT da simulação cria uma regra. Com a guarda única
    ("tem regra?"), a instância passava a ser considerada já enriquecida e
    nenhum outro histórico era semeado numa segunda execução.
    """
    db.add(AlertRule(
        instance_id=demo_instance.id,
        name="Connection pool under load",
        metric_type="connections_ratio",
        condition="gt",
        threshold=40.0,
    ))
    db.commit()

    history.enrich_fleet(db)

    assert db.query(Backup).filter(Backup.instance_id == demo_instance.id).first()
    assert _series(db, demo_instance)


def test_backfill_seeds_p95_but_never_the_cumulative_counter(db, demo_instance):
    """
    p95 é grandeza instantânea e pode ser semeada; xact_commit é um CONTADOR
    cumulativo — uma série sintética dele produziria uma taxa de queries/s falsa
    exatamente na emenda com a medição real.
    """
    history._backfill_metrics(db, demo_instance, idx=0)

    assert _series(db, demo_instance, "p95_query_latency_ms")
    assert not _series(db, demo_instance, "xact_commit")


def test_seeded_p95_follows_the_traffic_curve(db, demo_instance):
    """Latência mais alta sob carga: uma linha reta não ensinaria nada."""
    history._backfill_metrics(db, demo_instance, idx=0)

    values = [p.value for p in _series(db, demo_instance, "p95_query_latency_ms")]
    assert min(values) < max(values)
