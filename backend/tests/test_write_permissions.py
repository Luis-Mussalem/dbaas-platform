"""
The write gate: members observe, admins operate.

Every endpoint that CHANGES state requires a company admin (or the platform
superuser); everything that only READS is open to any member of the company. The
rule is stated once in core.dependencies.get_current_company_admin — this module
is the executable version of it.

Why it matters: before this, `role` only guarded employee management and the
audit trail, so an ordinary member could stop production, delete an instance, or
restore a backup over a live database — the last one silently replacing every row
with an old dump. The demo fleet makes the boundary visible: `admin@<company>`
operates, `user1..4@<company>` observe.

The tests are deliberately shallow (status codes, not effects): the behaviour of
each operation is covered by its own module. What is asserted here is only WHO is
let through, on every mutating route the API exposes, so that a route added later
without a dependency shows up as a failure.
"""
import uuid

import pytest

from src.models.backup import Backup, BackupStatus, BackupStrategy
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.models.user import UserRole

V1 = "/api/v1"


@pytest.fixture
def company(make_company):
    return make_company(name="Write Co")


@pytest.fixture
def member(auth_headers, company):
    headers, user = auth_headers(
        email="member@write.co", company_id=company.id, role=UserRole.MEMBER
    )
    return headers


@pytest.fixture
def admin(auth_headers, company):
    headers, user = auth_headers(
        email="admin@write.co", company_id=company.id, role=UserRole.ADMIN
    )
    return headers


@pytest.fixture
def instance(db, company):
    inst = DatabaseInstance(
        name="write-db", status=InstanceStatus.RUNNING, company_id=company.id
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


@pytest.fixture
def backup(db, instance):
    b = Backup(
        instance_id=instance.id,
        strategy=BackupStrategy.LOGICAL,
        status=BackupStatus.COMPLETED,
        file_path="/tmp/does-not-matter.dump",
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def _mutating_routes(instance_id, backup_id):
    """
    (method, path, body) for every state-changing route reachable with an
    instance and a backup in hand. Kept as data so the two tests below — member
    is refused, admin is not — walk exactly the same list.
    """
    inst = f"{V1}/instances/{instance_id}"
    return [
        ("post", f"{V1}/instances", {"name": "new-db"}),
        ("patch", inst, {"notes": "edited"}),
        ("patch", f"{inst}/status", {"action": "stop"}),
        ("delete", inst, None),
        ("post", f"{inst}/backups", {"strategy": "logical"}),
        ("delete", f"{V1}/backups/{backup_id}", None),
        ("post", f"{V1}/backups/{backup_id}/restore", None),
        ("post", f"{inst}/schedules", {"cron_expression": "0 2 * * *"}),
        ("post", f"{inst}/maintenance/run", {"task_type": "analyze"}),
        ("post", f"{inst}/maintenance/schedules", {"task_type": "analyze", "cron_expression": "0 3 * * *"}),
        ("post", f"{inst}/alerts/rules", {
            "name": "r", "metric_type": "cache_hit_ratio",
            "condition": "lt", "threshold": 95.0,
        }),
        ("post", f"{inst}/alerts/seed-defaults", None),
        ("post", f"{inst}/replicas", {}),
    ]


def _read_routes(instance_id):
    """The read surface a member keeps. Same shape, opposite expectation."""
    inst = f"{V1}/instances/{instance_id}"
    return [
        f"{V1}/instances",
        f"{V1}/instances/fleet-summary",
        inst,
        f"{inst}/metrics",
        f"{inst}/metrics/history?metric=xact_commit",
        f"{inst}/backups",
        f"{inst}/maintenance",
        f"{inst}/maintenance/schedules",
        f"{inst}/config-recommendations",
        f"{inst}/alerts/rules",
        f"{inst}/alerts/events",
        f"{inst}/replicas",
        f"{V1}/alerts/events",
        f"{V1}/admin/dashboard",
    ]


# --------------------------------------------------------------------------- #
# Members are refused on every mutating route
# --------------------------------------------------------------------------- #


def test_member_is_refused_on_every_mutating_route(client, member, instance, backup):
    refused = []
    for method, path, body in _mutating_routes(instance.id, backup.id):
        resp = getattr(client, method)(
            path, headers=member, **({"json": body} if body is not None else {})
        )
        if resp.status_code != 403:
            refused.append((method.upper(), path, resp.status_code))

    assert refused == [], f"these mutating routes let a member through: {refused}"


def test_member_keeps_the_whole_read_surface(client, member, instance):
    """
    The other half of the rule. A read-only role that cannot read is just a
    broken account — the point of the gate is that observing stays open.
    """
    blocked = []
    for path in _read_routes(instance.id):
        resp = client.get(path, headers=member)
        if resp.status_code != 200:
            blocked.append((path, resp.status_code))

    assert blocked == [], f"these read routes refused a member: {blocked}"


def test_member_can_still_use_the_sql_console(client, member, db, company):
    """
    The SQL console is a POST, but it is read-only by construction (sql_guard
    rejects anything that is not a single SELECT), so it stays with the readers.

    The 422 is the whole point: the request got past the write gate and was
    stopped by the SELECT-only guard instead. It needs a connection_uri only
    because the router checks for one before reaching the guard — the guard
    raises before the connection is ever opened, so nothing is dialled.
    """
    from src.core.encryption import encrypt_value

    inst = DatabaseInstance(
        name="console-db",
        status=InstanceStatus.RUNNING,
        company_id=company.id,
        connection_uri=encrypt_value("postgresql://u:p@127.0.0.1:5433/appdb"),
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)

    resp = client.post(
        f"{V1}/instances/{inst.id}/query",
        headers=member,
        json={"query": "DELETE FROM orders"},
    )
    assert resp.status_code == 422
    assert "SELECT" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# Admins get through the gate
# --------------------------------------------------------------------------- #


def test_admin_passes_the_write_gate(client, admin, instance, backup, fake_provisioner):
    """
    The same list must NOT answer 403 for an admin. Anything else (409 because
    the instance is not in the right state, 422 because the body is minimal) means
    the request got past authorization, which is all this asserts.

    `fake_provisioner` is not optional: several of these routes provision for real,
    and without it the suite leaves live PostgreSQL containers behind.
    """
    gated = []
    for method, path, body in _mutating_routes(instance.id, backup.id):
        resp = getattr(client, method)(
            path, headers=admin, **({"json": body} if body is not None else {})
        )
        if resp.status_code == 403:
            gated.append((method.upper(), path))

    assert gated == [], f"the write gate refused an admin on: {gated}"


def test_superuser_passes_the_write_gate(client, auth_headers, instance, backup, fake_provisioner):
    headers, _ = auth_headers(email="root@example.com", is_superuser=True)

    gated = []
    for method, path, body in _mutating_routes(instance.id, backup.id):
        resp = getattr(client, method)(
            path, headers=headers, **({"json": body} if body is not None else {})
        )
        if resp.status_code == 403:
            gated.append((method.upper(), path))

    assert gated == [], f"the write gate refused the superuser on: {gated}"


# --------------------------------------------------------------------------- #
# The gate is not a substitute for tenant scoping
# --------------------------------------------------------------------------- #


def test_admin_of_another_company_still_gets_404(client, auth_headers, make_company, instance):
    """
    Defense in depth: passing the role check does not grant reach. An admin is an
    admin of THEIR company — the scoping layer (get_instance_or_404) answers 404,
    not 403, so the instance's existence isn't leaked either.
    """
    other = make_company(name="Somewhere Else")
    headers, _ = auth_headers(
        email="admin@elsewhere.co", company_id=other.id, role=UserRole.ADMIN
    )

    resp = client.delete(f"{V1}/instances/{instance.id}", headers=headers)
    assert resp.status_code == 404


def test_unauthenticated_is_401_not_403(client, instance):
    """The gate runs after authentication, so no token is still a 401."""
    resp = client.delete(f"{V1}/instances/{instance.id}")
    assert resp.status_code == 401


def test_unknown_instance_is_404_for_an_admin(client, admin):
    resp = client.delete(f"{V1}/instances/{uuid.uuid4()}", headers=admin)
    assert resp.status_code == 404
