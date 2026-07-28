"""
RBAC tests — company-admin delegation (PHASE 11 — Stage D).

Covers the intra-company `role` axis (admin/member), orthogonal to `is_superuser`
(the platform axis). A company admin only manages employees of their own
company; the superuser retains full cross-company power.

Relevant error postures:
- a target invisible to the company admin (another company, or the target is a superuser) → 404
  (doesn't leak existence);
- missing the role entirely (member on an admin route) → 403.
"""
from src.models.user import UserRole
from tests.conftest import TEST_PASSWORD

API = "/api/v1/users"
STRONG_PASSWORD = "ValidPass123!"


# --------------------------------------------------------------------------- #
# Happy paths — company admin manages their own company
# --------------------------------------------------------------------------- #


def test_company_admin_creates_member_in_own_company(client, auth_headers, make_company):
    company = make_company(name="Acme")
    headers, _ = auth_headers(
        email="admin@acme.com", company_id=company.id, role=UserRole.ADMIN
    )

    resp = client.post(
        API,
        headers=headers,
        json={"email": "member@acme.com", "password": STRONG_PASSWORD},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "member@acme.com"
    assert body["company_id"] == str(company.id)
    assert body["role"] == "member"
    assert body["is_superuser"] is False


def test_company_admin_creates_admin_in_own_company(client, auth_headers, make_company):
    company = make_company(name="Acme")
    headers, _ = auth_headers(
        email="admin@acme.com", company_id=company.id, role=UserRole.ADMIN
    )

    resp = client.post(
        API,
        headers=headers,
        json={"email": "admin2@acme.com", "password": STRONG_PASSWORD, "role": "admin"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "admin"
    assert resp.json()["company_id"] == str(company.id)


def test_company_admin_create_forces_own_company(client, auth_headers, make_company):
    """company_id missing from the payload → forced to the admin's company."""
    company = make_company(name="Acme")
    headers, _ = auth_headers(
        email="admin@acme.com", company_id=company.id, role=UserRole.ADMIN
    )

    resp = client.post(
        API,
        headers=headers,
        json={"email": "member@acme.com", "password": STRONG_PASSWORD},
    )
    assert resp.status_code == 201
    assert resp.json()["company_id"] == str(company.id)


def test_company_admin_lists_only_own_company(
    client, auth_headers, make_company, make_user
):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    make_user(email="other@b.com", company_id=company_b.id)
    headers, _ = auth_headers(
        email="admin@a.com", company_id=company_a.id, role=UserRole.ADMIN
    )

    resp = client.get(API, headers=headers)
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert emails == {"admin@a.com"}
    assert "other@b.com" not in emails


def test_company_admin_lists_own_company_ignores_filter(
    client, auth_headers, make_company, make_user
):
    """Even passing ?company_id=<other>, the admin only sees their own company."""
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    make_user(email="other@b.com", company_id=company_b.id)
    headers, _ = auth_headers(
        email="admin@a.com", company_id=company_a.id, role=UserRole.ADMIN
    )

    resp = client.get(f"{API}?company_id={company_b.id}", headers=headers)
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert emails == {"admin@a.com"}


def test_company_admin_updates_member_email(
    client, auth_headers, make_company, make_user
):
    company = make_company(name="Acme")
    member = make_user(email="member@acme.com", company_id=company.id)
    headers, _ = auth_headers(
        email="admin@acme.com", company_id=company.id, role=UserRole.ADMIN
    )

    resp = client.patch(
        f"{API}/{member.id}/admin",
        headers=headers,
        json={"email": "renamed@acme.com"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "renamed@acme.com"


def test_company_admin_promotes_member_to_admin(
    client, auth_headers, make_company, make_user
):
    company = make_company(name="Acme")
    member = make_user(email="member@acme.com", company_id=company.id)
    headers, _ = auth_headers(
        email="admin@acme.com", company_id=company.id, role=UserRole.ADMIN
    )

    resp = client.patch(
        f"{API}/{member.id}/admin",
        headers=headers,
        json={"role": "admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


def test_company_admin_deactivates_member(
    client, auth_headers, make_company, make_user
):
    company = make_company(name="Acme")
    member = make_user(email="member@acme.com", company_id=company.id)
    headers, _ = auth_headers(
        email="admin@acme.com", company_id=company.id, role=UserRole.ADMIN
    )

    resp = client.patch(
        f"{API}/{member.id}/admin",
        headers=headers,
        json={"is_active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


# --------------------------------------------------------------------------- #
# Role gate — member cannot use admin routes
# --------------------------------------------------------------------------- #


def test_member_cannot_list_users(client, auth_headers, make_company):
    company = make_company()
    headers, _ = auth_headers(
        email="member@acme.com", company_id=company.id, role=UserRole.MEMBER
    )

    resp = client.get(API, headers=headers)
    assert resp.status_code == 403


def test_member_cannot_create_user(client, auth_headers, make_company):
    company = make_company()
    headers, _ = auth_headers(
        email="member@acme.com", company_id=company.id, role=UserRole.MEMBER
    )

    resp = client.post(
        API,
        headers=headers,
        json={"email": "x@acme.com", "password": STRONG_PASSWORD},
    )
    assert resp.status_code == 403


def test_member_cannot_admin_patch(client, auth_headers, make_company, make_user):
    company = make_company()
    target = make_user(email="t@acme.com", company_id=company.id)
    headers, _ = auth_headers(
        email="member@acme.com", company_id=company.id, role=UserRole.MEMBER
    )

    resp = client.patch(
        f"{API}/{target.id}/admin",
        headers=headers,
        json={"is_active": False},
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Escalation guards — company admin cannot escalate privileges
# --------------------------------------------------------------------------- #


def test_company_admin_cannot_create_superuser(client, auth_headers, make_company):
    company = make_company()
    headers, _ = auth_headers(
        email="admin@acme.com", company_id=company.id, role=UserRole.ADMIN
    )

    resp = client.post(
        API,
        headers=headers,
        json={
            "email": "evil@acme.com",
            "password": STRONG_PASSWORD,
            "is_superuser": True,
        },
    )
    assert resp.status_code == 403
    assert "superuser" in resp.json()["detail"].lower()


def test_company_admin_cannot_create_in_foreign_company(
    client, auth_headers, make_company
):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    headers, _ = auth_headers(
        email="admin@a.com", company_id=company_a.id, role=UserRole.ADMIN
    )

    resp = client.post(
        API,
        headers=headers,
        json={
            "email": "x@b.com",
            "password": STRONG_PASSWORD,
            "company_id": str(company_b.id),
        },
    )
    assert resp.status_code == 403
    assert "another company" in resp.json()["detail"].lower()


def test_company_admin_cannot_grant_superuser_via_update(
    client, auth_headers, make_company, make_user
):
    company = make_company()
    member = make_user(email="member@acme.com", company_id=company.id)
    headers, _ = auth_headers(
        email="admin@acme.com", company_id=company.id, role=UserRole.ADMIN
    )

    resp = client.patch(
        f"{API}/{member.id}/admin",
        headers=headers,
        json={"is_superuser": True},
    )
    assert resp.status_code == 403
    assert "superuser flag" in resp.json()["detail"].lower()


def test_company_admin_cannot_move_user_to_foreign_company(
    client, auth_headers, make_company, make_user
):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    member = make_user(email="member@a.com", company_id=company_a.id)
    headers, _ = auth_headers(
        email="admin@a.com", company_id=company_a.id, role=UserRole.ADMIN
    )

    resp = client.patch(
        f"{API}/{member.id}/admin",
        headers=headers,
        json={"company_id": str(company_b.id)},
    )
    assert resp.status_code == 403
    assert "another company" in resp.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# 404 postures — invisible target (doesn't leak existence)
# --------------------------------------------------------------------------- #


def test_company_admin_update_foreign_user_returns_404(
    client, auth_headers, make_company, make_user
):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    foreign = make_user(email="foreign@b.com", company_id=company_b.id)
    headers, _ = auth_headers(
        email="admin@a.com", company_id=company_a.id, role=UserRole.ADMIN
    )

    resp = client.patch(
        f"{API}/{foreign.id}/admin",
        headers=headers,
        json={"is_active": False},
    )
    assert resp.status_code == 404


def test_company_admin_update_superuser_target_returns_404(
    client, auth_headers, make_company, make_user
):
    company = make_company()
    su = make_user(email="su@example.com", is_superuser=True)
    headers, _ = auth_headers(
        email="admin@acme.com", company_id=company.id, role=UserRole.ADMIN
    )

    resp = client.patch(
        f"{API}/{su.id}/admin",
        headers=headers,
        json={"is_active": False},
    )
    assert resp.status_code == 404


def test_company_admin_reads_their_own_employee(
    client, auth_headers, make_company, make_user
):
    """
    An admin can GET a colleague by id — the same set they already see in
    `GET /users` and can edit via `PATCH /users/{id}/admin`. Refusing it here was
    an inconsistency, not a protection.
    """
    company = make_company(name="Company A")
    employee = make_user(email="employee@a.com", company_id=company.id)
    headers, _ = auth_headers(
        email="admin@a.com", company_id=company.id, role=UserRole.ADMIN
    )

    resp = client.get(f"{API}/{employee.id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "employee@a.com"


def test_company_admin_get_foreign_user_returns_404(
    client, auth_headers, make_company, make_user
):
    """
    Reaching outside the company is 404, not 403 — the same posture as the rest of
    the tenant boundary. 403 would confirm that the account exists.
    """
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    foreign = make_user(email="foreign@b.com", company_id=company_b.id)
    headers, _ = auth_headers(
        email="admin@a.com", company_id=company_a.id, role=UserRole.ADMIN
    )

    resp = client.get(f"{API}/{foreign.id}", headers=headers)
    assert resp.status_code == 404


def test_company_admin_get_superuser_returns_404(
    client, auth_headers, make_company, make_user
):
    """A platform superuser is invisible to a company admin, by id as well."""
    company = make_company(name="Company A")
    root = make_user(email="root@example.com", is_superuser=True)
    headers, _ = auth_headers(
        email="admin@a.com", company_id=company.id, role=UserRole.ADMIN
    )

    resp = client.get(f"{API}/{root.id}", headers=headers)
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Guard last-company-admin
# --------------------------------------------------------------------------- #


def test_cannot_demote_last_company_admin(
    client, auth_headers, make_company, make_user
):
    company = make_company(name="Acme")
    # the admin to be deactivated is the company's only active admin
    admin = make_user(
        email="onlyadmin@acme.com", company_id=company.id, role=UserRole.ADMIN
    )
    su_headers, _ = auth_headers(email="su@example.com", is_superuser=True)

    resp = client.patch(
        f"{API}/{admin.id}/admin",
        headers=su_headers,
        json={"role": "member"},
    )
    assert resp.status_code == 400
    assert "last active admin" in resp.json()["detail"].lower()


def test_cannot_deactivate_last_company_admin(
    client, auth_headers, make_company, make_user
):
    company = make_company(name="Acme")
    admin = make_user(
        email="onlyadmin@acme.com", company_id=company.id, role=UserRole.ADMIN
    )
    su_headers, _ = auth_headers(email="su@example.com", is_superuser=True)

    resp = client.patch(
        f"{API}/{admin.id}/admin",
        headers=su_headers,
        json={"is_active": False},
    )
    assert resp.status_code == 400
    assert "last active admin" in resp.json()["detail"].lower()


def test_can_demote_admin_when_another_exists(
    client, auth_headers, make_company, make_user
):
    company = make_company(name="Acme")
    admin1 = make_user(
        email="admin1@acme.com", company_id=company.id, role=UserRole.ADMIN
    )
    make_user(email="admin2@acme.com", company_id=company.id, role=UserRole.ADMIN)
    su_headers, _ = auth_headers(email="su@example.com", is_superuser=True)

    resp = client.patch(
        f"{API}/{admin1.id}/admin",
        headers=su_headers,
        json={"role": "member"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "member"


# --------------------------------------------------------------------------- #
# Cross-company isolation (two admins, two companies)
# --------------------------------------------------------------------------- #


def test_two_company_admins_are_isolated(
    client, auth_headers, make_company, make_user
):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    make_user(email="member-a@a.com", company_id=company_a.id)
    make_user(email="member-b@b.com", company_id=company_b.id)

    headers_a, _ = auth_headers(
        email="admin@a.com", company_id=company_a.id, role=UserRole.ADMIN
    )
    headers_b, _ = auth_headers(
        email="admin@b.com", company_id=company_b.id, role=UserRole.ADMIN
    )

    emails_a = {u["email"] for u in client.get(API, headers=headers_a).json()}
    emails_b = {u["email"] for u in client.get(API, headers=headers_b).json()}

    assert "member-a@a.com" in emails_a and "member-b@b.com" not in emails_a
    assert "member-b@b.com" in emails_b and "member-a@a.com" not in emails_b


# --------------------------------------------------------------------------- #
# Member sanity check and old-token regression
# --------------------------------------------------------------------------- #


def test_member_role_is_default(client, auth_headers, make_company):
    """A user created with no explicit role is born as member (server_default)."""
    company = make_company()
    su_headers, _ = auth_headers(email="su@example.com", is_superuser=True)

    resp = client.post(
        API,
        headers=su_headers,
        json={
            "email": "default@acme.com",
            "password": STRONG_PASSWORD,
            "company_id": str(company.id),
        },
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "member"


def test_member_can_still_self_get_and_patch(
    client, auth_headers, make_company
):
    company = make_company()
    headers, me = auth_headers(
        email="member@acme.com", company_id=company.id, role=UserRole.MEMBER
    )

    get_resp = client.get(f"{API}/{me.id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["email"] == "member@acme.com"

    patch_resp = client.patch(
        f"{API}/{me.id}",
        headers=headers,
        json={"email": "renamed@acme.com", "current_password": TEST_PASSWORD},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["email"] == "renamed@acme.com"
