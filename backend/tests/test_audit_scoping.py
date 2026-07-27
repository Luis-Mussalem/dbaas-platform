"""
Audit scoping tests (PHASE 11 — Stage E).

Ensure the audit log is multi-tenant safe:
- company-admin sees only their own company's logs;
- member gets 403;
- superuser with no header sees everything (incl. NULL-company entries);
- superuser with X-Company-Id sees only that company;
- write_audit_log correctly stamps the company_id.
"""
from src.models.audit_log import AuditLog
from src.models.user import UserRole
from src.services import admin as admin_service

AUDIT = "/api/v1/admin/audit-log"


# --------------------------------------------------------------------------- #
# Access / authorization
# --------------------------------------------------------------------------- #


def test_audit_log_requires_auth(client):
    assert client.get(AUDIT).status_code == 401


def test_member_gets_403(client, auth_headers, make_company):
    company = make_company()
    headers, _ = auth_headers(email="member@example.com", company_id=company.id, role=UserRole.MEMBER)
    assert client.get(AUDIT, headers=headers).status_code == 403


def test_company_admin_gets_200(client, auth_headers, make_company):
    company = make_company()
    headers, _ = auth_headers(email="admin@example.com", company_id=company.id, role=UserRole.ADMIN)
    assert client.get(AUDIT, headers=headers).status_code == 200


# --------------------------------------------------------------------------- #
# Scoping de leitura
# --------------------------------------------------------------------------- #


def test_company_admin_sees_only_own_company_entries(client, auth_headers, make_company, db):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")

    admin_service.write_audit_log(db, action="login", resource_type="auth", company_id=company_a.id)
    admin_service.write_audit_log(db, action="backup_created", resource_type="backup", company_id=company_b.id)

    headers_a, _ = auth_headers(email="admin_a@example.com", company_id=company_a.id, role=UserRole.ADMIN)
    resp = client.get(AUDIT, headers=headers_a)
    assert resp.status_code == 200
    actions = [e["action"] for e in resp.json()]
    assert actions == ["login"]


def test_company_admin_excludes_null_company_entries(client, auth_headers, make_company, db):
    company = make_company()
    # Entrada com company_id (do admin) e entrada de sistema (NULL)
    admin_service.write_audit_log(db, action="instance_created", resource_type="instance", company_id=company.id)
    admin_service.write_audit_log(db, action="register", resource_type="user")  # company_id=None

    headers, _ = auth_headers(email="admin@example.com", company_id=company.id, role=UserRole.ADMIN)
    resp = client.get(AUDIT, headers=headers)
    assert resp.status_code == 200
    actions = [e["action"] for e in resp.json()]
    assert actions == ["instance_created"]
    assert "register" not in actions


def test_superuser_without_header_sees_all(client, auth_headers, make_company, db):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    admin_service.write_audit_log(db, action="login", resource_type="auth", company_id=company_a.id)
    admin_service.write_audit_log(db, action="logout", resource_type="auth", company_id=company_b.id)
    admin_service.write_audit_log(db, action="register", resource_type="user")  # NULL

    headers, _ = auth_headers(email="root@example.com", is_superuser=True)
    resp = client.get(AUDIT, headers=headers)
    assert resp.status_code == 200
    actions = {e["action"] for e in resp.json()}
    assert actions == {"login", "logout", "register"}


def test_superuser_with_company_header_sees_only_that_company(client, auth_headers, make_company, db):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    admin_service.write_audit_log(db, action="login", resource_type="auth", company_id=company_a.id)
    admin_service.write_audit_log(db, action="logout", resource_type="auth", company_id=company_b.id)
    admin_service.write_audit_log(db, action="register", resource_type="user")  # NULL

    headers, _ = auth_headers(email="root@example.com", is_superuser=True)
    resp = client.get(AUDIT, headers={**headers, "X-Company-Id": str(company_b.id)})
    assert resp.status_code == 200
    actions = [e["action"] for e in resp.json()]
    assert actions == ["logout"]


# --------------------------------------------------------------------------- #
# Write-time stamping (via service)
# --------------------------------------------------------------------------- #


def test_write_audit_log_stamps_company_id(db, make_company):
    company = make_company()
    admin_service.write_audit_log(
        db,
        action="instance_created",
        resource_type="instance",
        company_id=company.id,
    )
    entry = db.query(AuditLog).filter(AuditLog.action == "instance_created").one()
    assert entry.company_id == company.id


def test_write_audit_log_null_company_for_system_events(db):
    admin_service.write_audit_log(db, action="login", resource_type="auth")
    entry = db.query(AuditLog).filter(AuditLog.action == "login").one()
    assert entry.company_id is None


# --------------------------------------------------------------------------- #
# Write-time stamping (via middleware — real HTTP request)
# --------------------------------------------------------------------------- #


def test_middleware_stamps_company_id_from_user(client, auth_headers, make_company, db):
    """
    A regular user logging out generates an AuditLog with their company's company_id.
    The middleware resolves the company_id by querying the database with the user_id extracted from the JWT.
    """
    company = make_company()
    headers, user = auth_headers(email="op@example.com", company_id=company.id, role=UserRole.MEMBER)

    resp = client.post("/api/v1/auth/logout", headers=headers)
    assert resp.status_code == 200

    entry = db.query(AuditLog).filter(AuditLog.action == "logout").first()
    assert entry is not None
    assert entry.company_id == company.id
    assert entry.user_id == user.id


def test_middleware_stamps_null_for_superuser_without_header(client, auth_headers, db):
    """Superuser sem X-Company-Id gera AuditLog com company_id=NULL."""
    headers, _ = auth_headers(email="root@example.com", is_superuser=True)

    resp = client.post("/api/v1/auth/logout", headers=headers)
    assert resp.status_code == 200

    entry = db.query(AuditLog).filter(AuditLog.action == "logout").first()
    assert entry is not None
    assert entry.company_id is None


def test_middleware_stamps_active_company_for_superuser_with_header(
    client, auth_headers, make_company, db
):
    """Superuser with an active X-Company-Id produces an AuditLog with that company_id."""
    company = make_company()
    headers, _ = auth_headers(email="root@example.com", is_superuser=True)

    resp = client.post(
        "/api/v1/auth/logout",
        headers={**headers, "X-Company-Id": str(company.id)},
    )
    assert resp.status_code == 200

    entry = db.query(AuditLog).filter(AuditLog.action == "logout").first()
    assert entry is not None
    assert entry.company_id == company.id


# --------------------------------------------------------------------------- #
# company_id exposto no schema de leitura
# --------------------------------------------------------------------------- #


def test_audit_log_response_includes_company_id(client, auth_headers, make_company, db):
    company = make_company()
    admin_service.write_audit_log(
        db, action="login", resource_type="auth", company_id=company.id
    )
    headers, _ = auth_headers(email="admin@example.com", company_id=company.id, role=UserRole.ADMIN)
    resp = client.get(AUDIT, headers=headers)
    assert resp.status_code == 200
    entry = resp.json()[0]
    assert "company_id" in entry
    assert entry["company_id"] == str(company.id)
