"""
Multi-tenant isolation tests (PHASE 11 — Stage A).

Ensure a regular user only sees/manages resources of their own company, that
the superuser sees all of them, and that derived resources (backups, alert events)
inherit the scoping of the owning instance.

Don't depend on Docker: instances are inserted directly via the ORM with company_id;
the only real creation test uses a fake provisioner (monkeypatch).
"""
import pytest

from src.models.alert import AlertCondition, AlertEvent, AlertRule, AlertSeverity
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.services.provisioning.types import ProvisionResult

API = "/api/v1/instances"


# --------------------------------------------------------------------------- #
# Helpers / fixtures
# --------------------------------------------------------------------------- #


def _seed_instance(db, company_id, name="db", status=InstanceStatus.STOPPED):
    inst = DatabaseInstance(name=name, status=status, company_id=company_id)
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


class _FakeProvisioner:
    """Minimal stub: doesn't touch Docker, returns a fixed ProvisionResult."""

    def create(self, instance_id, engine_version, memory_mb=None, cpu=None):
        return ProvisionResult(
            container_id="fake-container-id",
            host="127.0.0.1",
            port=55432,
            db_name="db_fake",
            db_user="inst_fake",
            db_password="fake-password",
            container_name="dbaas-inst-fake",
        )


@pytest.fixture
def fake_provisioner(monkeypatch):
    monkeypatch.setattr(
        "src.services.instance.get_provisioner", lambda: _FakeProvisioner()
    )


# --------------------------------------------------------------------------- #
# Listing / reading instances
# --------------------------------------------------------------------------- #


def test_list_instances_scoped_to_own_company(client, auth_headers, make_company, db):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    headers, _ = auth_headers(email="a@example.com", company_id=company_a.id)
    _seed_instance(db, company_a.id, name="a1")
    _seed_instance(db, company_a.id, name="a2")
    _seed_instance(db, company_b.id, name="b1")

    resp = client.get(API, headers=headers)
    assert resp.status_code == 200
    assert {i["name"] for i in resp.json()} == {"a1", "a2"}


def test_get_other_company_instance_returns_404(client, auth_headers, make_company, db):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    headers, _ = auth_headers(email="a@example.com", company_id=company_a.id)
    b_inst = _seed_instance(db, company_b.id, name="b1")

    resp = client.get(f"{API}/{b_inst.id}", headers=headers)
    assert resp.status_code == 404


def test_superuser_sees_all_companies(client, auth_headers, make_company, db):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    _seed_instance(db, company_a.id, name="a1")
    _seed_instance(db, company_b.id, name="b1")
    headers, _ = auth_headers(email="root@example.com", is_superuser=True)

    resp = client.get(API, headers=headers)
    assert resp.status_code == 200
    assert {"a1", "b1"} <= {i["name"] for i in resp.json()}


# --------------------------------------------------------------------------- #
# Creation assigns the creator's company
# --------------------------------------------------------------------------- #


def test_created_instance_belongs_to_creator_company(
    client, auth_headers, make_company, fake_provisioner
):
    company_a = make_company(name="Company A")
    headers, _ = auth_headers(email="a@example.com", company_id=company_a.id)

    resp = client.post(
        API,
        headers=headers,
        json={"name": "fresh-db", "engine_version": "16"},
    )
    assert resp.status_code == 201
    assert resp.json()["company_id"] == str(company_a.id)


# --------------------------------------------------------------------------- #
# Derived resources inherit the scoping
# --------------------------------------------------------------------------- #


def test_other_company_backups_endpoint_returns_404(
    client, auth_headers, make_company, db
):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    headers, _ = auth_headers(email="a@example.com", company_id=company_a.id)
    b_inst = _seed_instance(db, company_b.id, name="b1")

    resp = client.get(f"{API}/{b_inst.id}/backups", headers=headers)
    assert resp.status_code == 404


def test_global_alert_events_scoped_by_company(
    client, auth_headers, make_company, db
):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    a_inst = _seed_instance(db, company_a.id, name="a1")
    b_inst = _seed_instance(db, company_b.id, name="b1")

    # One rule+event in each company.
    for inst in (a_inst, b_inst):
        rule = AlertRule(
            instance_id=inst.id,
            name="r",
            metric_type="backup_age_hours",
            condition=AlertCondition.GT,
            threshold=24.0,
            severity=AlertSeverity.CRITICAL,
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        db.add(
            AlertEvent(
                rule_id=rule.id,
                instance_id=inst.id,
                current_value=99,
                message=f"event-{inst.name}",
            )
        )
    db.commit()

    headers_a, _ = auth_headers(email="a@example.com", company_id=company_a.id)
    resp = client.get("/api/v1/alerts/events", headers=headers_a)
    assert resp.status_code == 200
    messages = {e["message"] for e in resp.json()}
    assert messages == {"event-a1"}  # does NOT see company B's event

    headers_su, _ = auth_headers(email="root@example.com", is_superuser=True)
    resp_su = client.get("/api/v1/alerts/events", headers=headers_su)
    assert {"event-a1", "event-b1"} <= {e["message"] for e in resp_su.json()}


# --------------------------------------------------------------------------- #
# Stage B — superuser's active company (X-Company-Id header)
# --------------------------------------------------------------------------- #


def test_superuser_active_company_header_filters(client, auth_headers, make_company, db):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    _seed_instance(db, company_a.id, name="a1")
    _seed_instance(db, company_b.id, name="b1")
    headers, _ = auth_headers(email="root@example.com", is_superuser=True)

    # With company B active, the superuser only sees B's instances.
    resp = client.get(API, headers={**headers, "X-Company-Id": str(company_b.id)})
    assert resp.status_code == 200
    assert {i["name"] for i in resp.json()} == {"b1"}


def test_regular_user_ignores_company_header(client, auth_headers, make_company, db):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    _seed_instance(db, company_a.id, name="a1")
    _seed_instance(db, company_b.id, name="b1")
    headers, _ = auth_headers(email="a@example.com", company_id=company_a.id)

    # A regular user tries to forge company B in the header — should be ignored.
    resp = client.get(API, headers={**headers, "X-Company-Id": str(company_b.id)})
    assert resp.status_code == 200
    assert {i["name"] for i in resp.json()} == {"a1"}
