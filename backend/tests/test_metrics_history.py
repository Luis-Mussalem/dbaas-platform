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
