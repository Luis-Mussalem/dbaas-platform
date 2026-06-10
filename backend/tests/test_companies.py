"""
Testes do router /companies — a primeira superfície multi-tenant (PHASE 11).

O ponto central aqui é a AUTORIZAÇÃO: tanto GET quanto POST exigem
get_current_superuser. Um usuário comum autenticado deve receber 403; só o
superuser cria e lista empresas. Cobre também validação de payload e ordenação.
"""
from src.models.company import Company

API = "/api/v1/companies"


# --------------------------------------------------------------------------- #
# Autorização (superuser gate)
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
# Fluxo feliz (superuser)
# --------------------------------------------------------------------------- #


def test_superuser_creates_company(client, auth_headers, db):
    headers, _ = auth_headers(email="admin@example.com", is_superuser=True)
    resp = client.post(API, headers=headers, json={"name": "Acme Corp"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Acme Corp"
    assert "id" in body and "created_at" in body

    # Persistiu de fato no banco.
    assert db.query(Company).filter_by(name="Acme Corp").first() is not None


def test_superuser_lists_companies_ordered_by_name(client, auth_headers, db):
    headers, _ = auth_headers(email="admin@example.com", is_superuser=True)
    db.add_all([Company(name="Zeta"), Company(name="Alpha"), Company(name="Mid")])
    db.commit()

    resp = client.get(API, headers=headers)
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert names == ["Alpha", "Mid", "Zeta"]  # list_companies ordena por name


# --------------------------------------------------------------------------- #
# Validação de payload
# --------------------------------------------------------------------------- #


def test_create_company_rejects_empty_name(client, auth_headers):
    headers, _ = auth_headers(email="admin@example.com", is_superuser=True)
    resp = client.post(API, headers=headers, json={"name": ""})
    assert resp.status_code == 422  # min_length=1
