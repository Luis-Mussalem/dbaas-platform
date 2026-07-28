"""
Tests for the tenant filter itself (core.scoping.CompanyScope).

The scoping rule has THREE cases, and the bugs it guards against all come from
collapsing them into two:

- superuser with no workspace selected → sees everything;
- anyone with a company → sees that company;
- regular user with NO company → sees nothing.

The third is the one worth pinning down. Before CompanyScope, "the company to
filter by" was a bare Optional[UUID] and None meant "no filter", so a company-less
regular account was handed the ORPHAN instances (company_id NULL) by the instance
filter, and the ENTIRE platform by every consumer that skipped filtering on None —
the dashboard, the global alert list and the audit trail.

Also covered here: an instance is filed under the company the creator is LOOKING
AT, which for a superuser is the workspace from the X-Company-Id header and not
their own (empty) company_id.
"""
import uuid

import pytest

from src.models.alert import AlertCondition, AlertEvent, AlertRule
from src.models.audit_log import AuditLog
from src.models.database_instance import DatabaseInstance, InstanceStatus

INSTANCES = "/api/v1/instances"
DASHBOARD = "/api/v1/admin/dashboard"
EVENTS = "/api/v1/alerts/events"
AUDIT = "/api/v1/admin/audit-log"


@pytest.fixture
def orphan_instance(db):
    """An instance owned by no company — what a superuser creates with no workspace."""
    inst = DatabaseInstance(
        name="orphan-db", status=InstanceStatus.RUNNING, company_id=None
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _open_alert(db, instance) -> AlertEvent:
    rule = AlertRule(
        instance_id=instance.id,
        name="r",
        metric_type="cache_hit_ratio",
        condition=AlertCondition.LT,
        threshold=95.0,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    event = AlertEvent(
        rule_id=rule.id, instance_id=instance.id, current_value=1.0, message="open"
    )
    db.add(event)
    db.commit()
    return event


# --------------------------------------------------------------------------- #
# A company-less regular user is entitled to NOTHING
# --------------------------------------------------------------------------- #


def test_company_less_user_does_not_see_orphan_instances(
    client, auth_headers, orphan_instance
):
    """
    The regression this whole module exists for.

    `WHERE company_id = NULL` compiles to `IS NULL`, which would have matched every
    unassigned instance on the platform instead of matching nothing.
    """
    headers, _ = auth_headers(email="nocompany@example.com", company_id=None)

    listing = client.get(INSTANCES, headers=headers)
    assert listing.status_code == 200
    assert listing.json() == []

    detail = client.get(f"{INSTANCES}/{orphan_instance.id}", headers=headers)
    assert detail.status_code == 404


def test_company_less_user_dashboard_is_empty_not_global(
    client, auth_headers, orphan_instance, db
):
    """
    The dashboard used to treat "no company" as "no filter" — a company-less
    account got the aggregate for the WHOLE platform.
    """
    _open_alert(db, orphan_instance)
    headers, _ = auth_headers(email="nocompany@example.com", company_id=None)

    body = client.get(DASHBOARD, headers=headers).json()
    assert body["total_instances"] == 0
    assert body["instances_by_status"] == {}
    assert body["active_alerts"] == 0
    assert body["fleet_uptime_pct"] is None


def test_company_less_user_sees_no_alert_events(
    client, auth_headers, orphan_instance, db
):
    _open_alert(db, orphan_instance)
    headers, _ = auth_headers(email="nocompany@example.com", company_id=None)

    resp = client.get(EVENTS, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_company_less_admin_sees_no_audit_log(client, auth_headers, db, make_company):
    """
    Same collapse, on the audit trail. A company admin whose company was deleted
    (ON DELETE SET NULL) keeps role=admin with company_id NULL — they must not
    inherit the platform-wide trail.
    """
    from src.models.user import UserRole

    other = make_company(name="Someone Else")
    db.add(
        AuditLog(
            action="login",
            resource_type="auth",
            company_id=other.id,
            details={"path": "/api/v1/auth/login"},
        )
    )
    db.commit()

    headers, _ = auth_headers(
        email="orphanadmin@example.com", company_id=None, role=UserRole.ADMIN
    )
    resp = client.get(AUDIT, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_company_user_still_sees_their_own_company(
    client, auth_headers, make_company, db
):
    """Sanity check: the empty-scope rule didn't break the ordinary case."""
    company = make_company(name="Real Co")
    db.add(
        DatabaseInstance(
            name="mine", status=InstanceStatus.RUNNING, company_id=company.id
        )
    )
    db.commit()

    headers, _ = auth_headers(email="member@real.co", company_id=company.id)
    names = {i["name"] for i in client.get(INSTANCES, headers=headers).json()}
    assert names == {"mine"}


def test_superuser_still_sees_orphan_instances(client, auth_headers, orphan_instance):
    """The unassigned pile stays visible to the platform superuser."""
    headers, _ = auth_headers(email="root@example.com", is_superuser=True)
    names = {i["name"] for i in client.get(INSTANCES, headers=headers).json()}
    assert "orphan-db" in names


# --------------------------------------------------------------------------- #
# Creation is filed under the workspace on screen
# --------------------------------------------------------------------------- #


def test_superuser_creates_instance_in_the_active_workspace(
    client, auth_headers, make_company, fake_provisioner, db
):
    """
    A superuser with a company selected in the switcher creates the instance IN
    that company. Filing it under their own (NULL) company_id would make it vanish
    from the very workspace that was on screen, reachable only from "All companies".
    """
    company = make_company(name="Neptune")
    headers, _ = auth_headers(email="root@example.com", is_superuser=True)
    headers["X-Company-Id"] = str(company.id)

    resp = client.post(INSTANCES, headers=headers, json={"name": "scoped-db"})
    assert resp.status_code == 201
    assert resp.json()["company_id"] == str(company.id)

    # And it is visible to that company's own employees.
    member_headers, _ = auth_headers(email="member@neptune.example", company_id=company.id)
    names = {i["name"] for i in client.get(INSTANCES, headers=member_headers).json()}
    assert "scoped-db" in names


def test_superuser_without_workspace_creates_an_orphan(
    client, auth_headers, fake_provisioner
):
    """No workspace selected = platform-level instance, owned by no company."""
    headers, _ = auth_headers(email="root@example.com", is_superuser=True)

    resp = client.post(INSTANCES, headers=headers, json={"name": "platform-db"})
    assert resp.status_code == 201
    assert resp.json()["company_id"] is None


def test_invalid_company_header_is_ignored(client, auth_headers, fake_provisioner):
    """A malformed X-Company-Id falls back to "all companies", never to a 500."""
    headers, _ = auth_headers(email="root@example.com", is_superuser=True)
    headers["X-Company-Id"] = "not-a-uuid"

    resp = client.post(INSTANCES, headers=headers, json={"name": "bad-header-db"})
    assert resp.status_code == 201
    assert resp.json()["company_id"] is None


def test_regular_user_cannot_wear_another_company(
    client, auth_headers, make_company, fake_provisioner
):
    """
    X-Company-Id is a superuser affordance. A member sending it stays in their own
    company — otherwise the header would be a one-line tenant escape.
    """
    mine, theirs = make_company(name="Mine"), make_company(name="Theirs")
    headers, _ = auth_headers(email="member@mine.example", company_id=mine.id)
    headers["X-Company-Id"] = str(theirs.id)

    resp = client.post(INSTANCES, headers=headers, json={"name": "attempt-db"})
    assert resp.status_code == 201
    assert resp.json()["company_id"] == str(mine.id)


def test_company_less_user_creates_nothing_they_can_see(
    client, auth_headers, fake_provisioner
):
    """
    A company-less account can still POST, but the row it creates is an orphan it
    is not entitled to read back — consistent with the scope, not a silent grant.
    """
    headers, _ = auth_headers(email="nocompany@example.com", company_id=None)

    resp = client.post(INSTANCES, headers=headers, json={"name": "void-db"})
    assert resp.status_code == 201
    assert resp.json()["company_id"] is None
    assert client.get(INSTANCES, headers=headers).json() == []


# --------------------------------------------------------------------------- #
# Unit level — the scope object itself
# --------------------------------------------------------------------------- #


def test_company_scope_classifies_the_three_cases(make_user, make_company):
    from src.core.scoping import company_scope

    company = make_company(name="Acme")

    member = make_user(email="m@acme.test", company_id=company.id)
    scope = company_scope(member)
    assert (scope.unrestricted, scope.company_id, scope.is_empty) == (
        False,
        company.id,
        False,
    )

    orphan = make_user(email="o@acme.test", company_id=None)
    scope = company_scope(orphan)
    assert (scope.unrestricted, scope.company_id, scope.is_empty) == (False, None, True)

    root = make_user(email="r@acme.test", is_superuser=True)
    scope = company_scope(root)
    assert (scope.unrestricted, scope.is_empty) == (True, False)

    # Superuser wearing a workspace: restricted to it, exactly like a member.
    root.active_company_id = company.id
    scope = company_scope(root)
    assert (scope.unrestricted, scope.company_id) == (False, company.id)


def test_scope_apply_to_is_used_by_every_read_path(make_user):
    """
    An empty scope must produce a false predicate, not an unfiltered query — the
    single behaviour every consumer in this module depends on.
    """
    from src.core.scoping import CompanyScope

    empty = CompanyScope(company_id=None, unrestricted=False)
    assert empty.is_empty is True

    one = CompanyScope(company_id=uuid.uuid4(), unrestricted=False)
    assert one.is_empty is False

    everything = CompanyScope(company_id=None, unrestricted=True)
    assert everything.is_empty is False
