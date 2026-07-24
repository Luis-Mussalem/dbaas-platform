"""
Testes do endpoint de histórico de métricas (série temporal para sparklines).

GET /api/v1/instances/{id}/metrics/history?metric=&window= lê da tabela metrics
do banco da plataforma — não conecta ao banco monitorado. Cobrimos: filtragem
por janela, ordenação crescente, métrica inexistente (lista vazia), instância
inexistente (404) e janela inválida (422).
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.core.encryption import encrypt_value
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.metric import Metric


@pytest.fixture
def instance(db):
    inst = DatabaseInstance(
        name="hist-db",
        status=InstanceStatus.RUNNING,
        connection_uri=encrypt_value("postgresql://u:p@127.0.0.1:5433/appdb"),
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _url(instance_id) -> str:
    return f"/api/v1/instances/{instance_id}/metrics/history"


def test_history_requires_auth(client, instance):
    assert client.get(f"{_url(instance.id)}?metric=cache_hit_ratio").status_code == 401


def test_history_returns_points_in_window_ordered(client, auth_headers, instance, db):
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    db.add_all([
        # Fora da janela de 15m (não deve aparecer).
        Metric(instance_id=instance.id, metric_name="cache_hit_ratio", value=80.0,
               collected_at=now - timedelta(minutes=30)),
        # Dentro da janela (devem aparecer, em ordem crescente).
        Metric(instance_id=instance.id, metric_name="cache_hit_ratio", value=95.0,
               collected_at=now - timedelta(minutes=10)),
        Metric(instance_id=instance.id, metric_name="cache_hit_ratio", value=98.0,
               collected_at=now - timedelta(minutes=2)),
        # Outra métrica não deve vazar para o resultado.
        Metric(instance_id=instance.id, metric_name="connections_active", value=5.0,
               collected_at=now - timedelta(minutes=1)),
    ])
    db.commit()

    resp = client.get(f"{_url(instance.id)}?metric=cache_hit_ratio&window=15m", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["metric_name"] == "cache_hit_ratio"
    assert body["window"] == "15m"
    values = [p["value"] for p in body["points"]]
    assert values == [95.0, 98.0]  # filtrado por janela e ordenado por tempo


def test_history_wider_window_includes_more(client, auth_headers, instance, db):
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    db.add_all([
        Metric(instance_id=instance.id, metric_name="cache_hit_ratio", value=80.0,
               collected_at=now - timedelta(minutes=30)),
        Metric(instance_id=instance.id, metric_name="cache_hit_ratio", value=95.0,
               collected_at=now - timedelta(minutes=10)),
    ])
    db.commit()

    resp = client.get(f"{_url(instance.id)}?metric=cache_hit_ratio&window=1h", headers=headers)
    assert [p["value"] for p in resp.json()["points"]] == [80.0, 95.0]


def test_history_unknown_metric_returns_empty(client, auth_headers, instance):
    headers, _ = auth_headers()
    resp = client.get(f"{_url(instance.id)}?metric=does_not_exist", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["points"] == []


def test_history_unknown_instance_404(client, auth_headers):
    import uuid
    headers, _ = auth_headers()
    resp = client.get(f"{_url(uuid.uuid4())}?metric=cache_hit_ratio", headers=headers)
    assert resp.status_code == 404


def test_history_invalid_window_422(client, auth_headers, instance):
    headers, _ = auth_headers()
    resp = client.get(f"{_url(instance.id)}?metric=cache_hit_ratio&window=99y", headers=headers)
    assert resp.status_code == 422


def test_history_is_downsampled_to_a_stable_number_of_points(client, auth_headers, instance, db):
    """
    Uma janela de 24h com coleta a cada 5s (o que a simulação de uso faz) traz
    dezenas de milhares de amostras. O endpoint reamostra em baldes para o
    sparkline ter sempre a mesma resolução — e não virar uma serra.
    """
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    db.add_all([
        Metric(
            instance_id=instance.id,
            metric_name="connections_active",
            value=float(10 + (i % 2)),  # alterna 10/11: o ruído a suavizar
            collected_at=now - timedelta(seconds=5 * i),
        )
        for i in range(2000)  # ~2.7h de coleta a 5s
    ])
    db.commit()

    points = client.get(
        f"{_url(instance.id)}?metric=connections_active&window=24h", headers=headers
    ).json()["points"]

    assert 0 < len(points) <= 120, f"esperava série reamostrada, veio {len(points)}"
    # A média dentro do balde fica entre os extremos — a curva perde a serrilha,
    # não a escala.
    assert all(10.0 <= p["value"] <= 11.0 for p in points)
    # Ordem cronológica preservada.
    assert [p["collected_at"] for p in points] == sorted(p["collected_at"] for p in points)


def test_queries_per_second_is_derived_from_the_xact_commit_counter(
    client, auth_headers, instance, db
):
    """queries/s não é armazenado: a série vem da derivada do contador xact_commit."""
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    # Contador cumulativo crescendo +600 a cada 60s → 10 commits/s.
    db.add_all([
        Metric(instance_id=instance.id, metric_name="xact_commit", value=v,
               collected_at=now - timedelta(seconds=s))
        for v, s in [(1000, 180), (1600, 120), (2200, 60), (2800, 0)]
    ])
    db.commit()

    resp = client.get(
        f"{_url(instance.id)}?metric=queries_per_second&window=1h&points=60", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["metric_name"] == "queries_per_second"
    values = [p["value"] for p in body["points"]]
    assert values, "série derivada veio vazia"
    assert all(v == 10.0 for v in values)


def test_queries_per_second_series_skips_a_counter_reset(
    client, auth_headers, instance, db
):
    """Reset do Postgres reancora e NÃO emite ponto — nunca um pico nem um 0 falso."""
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    db.add_all([
        Metric(instance_id=instance.id, metric_name="xact_commit", value=v,
               collected_at=now - timedelta(seconds=s))
        for v, s in [(9000, 120), (50, 60), (650, 0)]  # reset entre -120s e -60s
    ])
    db.commit()

    resp = client.get(
        f"{_url(instance.id)}?metric=queries_per_second&window=1h&points=60", headers=headers
    )
    values = [p["value"] for p in resp.json()["points"]]
    assert values == [10.0]  # reset pulado; só o par pós-reset (50→650)/60s = 10


def test_queries_per_second_series_skips_a_stale_low_read(
    client, auth_headers, instance, db
):
    """
    Uma leitura stale (mergulho pequeno e transitório) é PULADA em vez de virar 0 e
    depois um pico: a linha interpola o buraco e o crescimento real reaparece no
    balde seguinte, medido sobre o intervalo maior.
    """
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    # +600/60s de crescimento real; o balde de -60s é STALE (2180 < 2200 de antes).
    db.add_all([
        Metric(instance_id=instance.id, metric_name="xact_commit", value=v,
               collected_at=now - timedelta(seconds=s))
        for v, s in [(1600, 180), (2200, 120), (2180, 60), (2800, 0)]
    ])
    db.commit()

    resp = client.get(
        f"{_url(instance.id)}?metric=queries_per_second&window=1h&points=60", headers=headers
    )
    values = [p["value"] for p in resp.json()["points"]]
    # 1600→2200 = +600/60 = 10; o stale 2180 é pulado; 2200→2800 = +600/120 = 5.
    # (window=1h/60 → baldes de 60s: a média móvel de 1 min é no-op aqui.)
    assert values == [10.0, 5.0]


def test_queries_per_second_series_is_smoothed_to_one_minute(
    client, auth_headers, instance, db
):
    """
    Em baldes curtos (15s), a taxa de uma carga em rajadas serrilha muito. A série
    passa por uma média móvel de ~1 min: um dente-de-serra 0/20 vira uma linha
    estável em ~10 (a taxa real média), mantendo um ponto por balde.
    """
    headers, _ = auth_headers()
    now = datetime.now(timezone.utc)
    # Um sample por balde de 15s; o contador cresce +300 a balde SIM, balde NÃO —
    # taxas cruas alternando 0 e 20 q/s.
    db.add_all([
        Metric(instance_id=instance.id, metric_name="xact_commit", value=v,
               collected_at=now - timedelta(seconds=s))
        for v, s in [(1900, 0), (1600, 15), (1600, 30), (1300, 45),
                     (1300, 60), (1000, 75), (1000, 90)]
    ])
    db.commit()

    # window=15m/60 → baldes de 15s → média móvel de 4 pontos (1 min).
    resp = client.get(
        f"{_url(instance.id)}?metric=queries_per_second&window=15m&points=60", headers=headers
    )
    values = [p["value"] for p in resp.json()["points"]]
    # A serra crua seria [0, 20, 0, 20, 0, 20]; alisada, a cauda assenta em 10 q/s.
    assert values[-3:] == [10.0, 10.0, 10.0]
    # E nenhum ponto alisado chega ao pico cru de 20 (o serrilhado sumiu).
    assert max(values) < 20.0
