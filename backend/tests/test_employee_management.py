"""
Testes de gerenciamento de funcionários (PHASE 11 — Stage C).

Cobre os endpoints superuser-gated de criação, listagem, atualização e
desativação de usuários. Usuários comuns devem receber 403 em todas as rotas
administrativas.
"""
API = "/api/v1/users"
STRONG_PASSWORD = "ValidPass123!"
WEAK_PASSWORD = "weak"


# --------------------------------------------------------------------------- #
# Criação de usuários (POST /users)
# --------------------------------------------------------------------------- #


def test_superuser_creates_user_in_company(client, auth_headers, make_company):
    company = make_company(name="Acme")
    headers, _ = auth_headers(email="su@example.com", is_superuser=True)

    resp = client.post(
        API,
        headers=headers,
        json={
            "email": "emp@acme.com",
            "password": STRONG_PASSWORD,
            "company_id": str(company.id),
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "emp@acme.com"
    assert body["company_id"] == str(company.id)
    assert body["is_superuser"] is False
    assert body["is_active"] is True


def test_create_user_without_company_non_superuser_returns_400(
    client, auth_headers, make_company
):
    headers, _ = auth_headers(email="su@example.com", is_superuser=True)

    resp = client.post(
        API,
        headers=headers,
        json={"email": "emp@acme.com", "password": STRONG_PASSWORD},
    )
    assert resp.status_code == 400
    assert "company_id" in resp.json()["detail"].lower()


def test_create_superuser_without_company_succeeds(client, auth_headers):
    headers, _ = auth_headers(email="su@example.com", is_superuser=True)

    resp = client.post(
        API,
        headers=headers,
        json={
            "email": "newsu@example.com",
            "password": STRONG_PASSWORD,
            "is_superuser": True,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["company_id"] is None
    assert resp.json()["is_superuser"] is True


def test_create_user_invalid_company_returns_400(client, auth_headers):
    import uuid

    headers, _ = auth_headers(email="su@example.com", is_superuser=True)

    resp = client.post(
        API,
        headers=headers,
        json={
            "email": "emp@acme.com",
            "password": STRONG_PASSWORD,
            "company_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 400
    assert "company" in resp.json()["detail"].lower()


def test_create_user_duplicate_email_returns_400(client, auth_headers, make_company):
    company = make_company()
    headers, _ = auth_headers(email="su@example.com", is_superuser=True)
    payload = {
        "email": "dup@acme.com",
        "password": STRONG_PASSWORD,
        "company_id": str(company.id),
    }

    client.post(API, headers=headers, json=payload)
    resp = client.post(API, headers=headers, json=payload)
    assert resp.status_code == 400


def test_create_user_weak_password_returns_422(client, auth_headers, make_company):
    company = make_company()
    headers, _ = auth_headers(email="su@example.com", is_superuser=True)

    resp = client.post(
        API,
        headers=headers,
        json={
            "email": "emp@acme.com",
            "password": WEAK_PASSWORD,
            "company_id": str(company.id),
        },
    )
    assert resp.status_code == 422


def test_regular_user_cannot_create_user(client, auth_headers, make_company):
    company = make_company()
    headers, _ = auth_headers(email="u@example.com", company_id=company.id)

    resp = client.post(
        API,
        headers=headers,
        json={
            "email": "emp@acme.com",
            "password": STRONG_PASSWORD,
            "company_id": str(company.id),
        },
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Listagem (GET /users)
# --------------------------------------------------------------------------- #


def test_list_users_filtered_by_company(client, auth_headers, make_company, db):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    headers, _ = auth_headers(email="su@example.com", is_superuser=True)

    # Cria um funcionário em A e outro em B via API
    client.post(
        API,
        headers=headers,
        json={
            "email": "a@example.com",
            "password": STRONG_PASSWORD,
            "company_id": str(company_a.id),
        },
    )
    client.post(
        API,
        headers=headers,
        json={
            "email": "b@example.com",
            "password": STRONG_PASSWORD,
            "company_id": str(company_b.id),
        },
    )

    resp = client.get(f"{API}?company_id={company_a.id}", headers=headers)
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert emails == {"a@example.com"}


def test_list_users_no_filter_returns_all(client, auth_headers, make_company):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    headers, _ = auth_headers(email="su@example.com", is_superuser=True)

    client.post(
        API,
        headers=headers,
        json={
            "email": "a@example.com",
            "password": STRONG_PASSWORD,
            "company_id": str(company_a.id),
        },
    )
    client.post(
        API,
        headers=headers,
        json={
            "email": "b@example.com",
            "password": STRONG_PASSWORD,
            "company_id": str(company_b.id),
        },
    )

    resp = client.get(API, headers=headers)
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert {"a@example.com", "b@example.com", "su@example.com"} <= emails


def test_regular_user_cannot_list_users(client, auth_headers, make_company):
    company = make_company()
    headers, _ = auth_headers(email="u@example.com", company_id=company.id)

    resp = client.get(API, headers=headers)
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Atualização admin (PATCH /users/{id}/admin)
# --------------------------------------------------------------------------- #


def test_admin_patch_reassigns_company(client, auth_headers, make_company):
    company_a = make_company(name="Company A")
    company_b = make_company(name="Company B")
    headers, _ = auth_headers(email="su@example.com", is_superuser=True)

    create_resp = client.post(
        API,
        headers=headers,
        json={
            "email": "emp@example.com",
            "password": STRONG_PASSWORD,
            "company_id": str(company_a.id),
        },
    )
    user_id = create_resp.json()["id"]

    resp = client.patch(
        f"{API}/{user_id}/admin",
        headers=headers,
        json={"company_id": str(company_b.id)},
    )
    assert resp.status_code == 200
    assert resp.json()["company_id"] == str(company_b.id)


def test_regular_user_cannot_admin_patch(client, auth_headers, make_company):
    import uuid

    company = make_company()
    headers, _ = auth_headers(email="u@example.com", company_id=company.id)

    resp = client.patch(
        f"{API}/{uuid.uuid4()}/admin",
        headers=headers,
        json={"is_active": False},
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Desativação
# --------------------------------------------------------------------------- #


def test_deactivated_user_cannot_login(client, auth_headers, make_company):
    company = make_company()
    su_headers, _ = auth_headers(email="su@example.com", is_superuser=True)

    # Cria funcionário
    create_resp = client.post(
        API,
        headers=su_headers,
        json={
            "email": "emp@acme.com",
            "password": STRONG_PASSWORD,
            "company_id": str(company.id),
        },
    )
    user_id = create_resp.json()["id"]

    # Desativa
    deact_resp = client.patch(
        f"{API}/{user_id}/admin",
        headers=su_headers,
        json={"is_active": False},
    )
    assert deact_resp.status_code == 200
    assert deact_resp.json()["is_active"] is False

    # Tenta login com as credenciais desativadas
    login_resp = client.post(
        "/api/v1/auth/login",
        data={"username": "emp@acme.com", "password": STRONG_PASSWORD},
    )
    assert login_resp.status_code == 401


# --------------------------------------------------------------------------- #
# Guards de lockout
# --------------------------------------------------------------------------- #


def test_superuser_cannot_deactivate_self(client, auth_headers):
    # Com dois superusers ativos, o guard last-superuser não dispara;
    # o self-lockout deve disparar.
    headers, su = auth_headers(email="su@example.com", is_superuser=True)
    client.post(
        API,
        headers=headers,
        json={"email": "su2@example.com", "password": STRONG_PASSWORD, "is_superuser": True},
    )

    resp = client.patch(
        f"{API}/{su.id}/admin",
        headers=headers,
        json={"is_active": False},
    )
    assert resp.status_code == 400
    assert "own account" in resp.json()["detail"].lower()


def test_superuser_cannot_demote_self(client, auth_headers):
    # Mesmo que seja o único superuser ativo, tentar demitir-se dispara 400.
    headers, su = auth_headers(email="su@example.com", is_superuser=True)

    resp = client.patch(
        f"{API}/{su.id}/admin",
        headers=headers,
        json={"is_superuser": False},
    )
    assert resp.status_code == 400


def test_cannot_deactivate_last_superuser(client, auth_headers, make_company):
    make_company()
    # O fixture auth_headers já cria um superuser (su@example.com)
    su_headers, su = auth_headers(email="su@example.com", is_superuser=True)

    # Cria um segundo superuser
    resp = client.post(
        API,
        headers=su_headers,
        json={
            "email": "su2@example.com",
            "password": STRONG_PASSWORD,
            "is_superuser": True,
        },
    )
    su2_id = resp.json()["id"]

    # Desativa o segundo — ok, ainda sobra o primeiro
    ok = client.patch(
        f"{API}/{su2_id}/admin",
        headers=su_headers,
        json={"is_active": False},
    )
    assert ok.status_code == 200

    # Agora tenta desativar o primeiro (último ativo) — deve falhar
    fail = client.patch(
        f"{API}/{su.id}/admin",
        headers=su_headers,
        json={"is_active": False},
    )
    assert fail.status_code == 400
    assert "last active superuser" in fail.json()["detail"].lower()
