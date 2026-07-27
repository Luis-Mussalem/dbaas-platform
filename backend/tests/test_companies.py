"""
Tests for the /companies router — the first multi-tenant surface (PHASE 11).

The central point here is AUTHORIZATION: both GET and POST require
get_current_superuser. An authenticated regular user should get 403; only the
superuser creates and lists companies. Also covers payload validation and ordering.
"""
from src.models.company import Company

API = "/api/v1/companies"


# --------------------------------------------------------------------------- #
# Authorization (superuser gate)
# --------------------------------------------------------------------------- #


def test_list_companies_requires_auth(client):
    resp = client.get(API)
    assert resp.status_code == 401


def test_list_companies_forbidden_for_regular_user(client, auth_headers):
    headers, _ = auth_headers(email="regular@example.com", is_superuser=False)
    resp = client.get(API, headers=headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Superuser privileges required"


def test_create_company_forbidden_for_regular_user(client, auth_headers):
    headers, _ = auth_headers(email="regular@example.com", is_superuser=False)
    resp = client.post(API, headers=headers, json={"name": "Acme"})
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Happy path (superuser)
# --------------------------------------------------------------------------- #


def test_superuser_creates_company(client, auth_headers, db):
    headers, _ = auth_headers(email="admin@example.com", is_superuser=True)
    resp = client.post(API, headers=headers, json={"name": "Acme Corp"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Acme Corp"
    assert "id" in body and "created_at" in body

    # Actually persisted to the database.
    assert db.query(Company).filter_by(name="Acme Corp").first() is not None


def test_superuser_lists_companies_ordered_by_name(client, auth_headers, db):
    headers, _ = auth_headers(email="admin@example.com", is_superuser=True)
    db.add_all([Company(name="Zeta"), Company(name="Alpha"), Company(name="Mid")])
    db.commit()

    resp = client.get(API, headers=headers)
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert names == ["Alpha", "Mid", "Zeta"]  # list_companies orders by name


# --------------------------------------------------------------------------- #
# Payload validation
# --------------------------------------------------------------------------- #


def test_create_company_rejects_empty_name(client, auth_headers):
    headers, _ = auth_headers(email="admin@example.com", is_superuser=True)
    resp = client.post(API, headers=headers, json={"name": ""})
    assert resp.status_code == 422  # min_length=1
