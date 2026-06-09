"""
Testes de autorização a nível de objeto em /users/{id}.

Travam o fix de segurança: um usuário só pode ler/alterar o PRÓPRIO registro;
o superuser pode ler qualquer um. Sem isso, qualquer usuário autenticado
acessaria os dados de outro pelo UUID (IDOR).
"""
from tests.conftest import TEST_PASSWORD

API = "/api/v1/users"


# --------------------------------------------------------------------------- #
# GET /users/{id}
# --------------------------------------------------------------------------- #


def test_get_own_user_ok(client, auth_headers):
    headers, user = auth_headers(email="self@example.com")
    resp = client.get(f"{API}/{user.id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "self@example.com"


def test_get_other_user_forbidden(client, auth_headers, make_user):
    # Regressão do IDOR: usuário comum NÃO pode ler outro usuário.
    headers, _ = auth_headers(email="attacker@example.com")
    victim = make_user(email="victim@example.com")
    resp = client.get(f"{API}/{victim.id}", headers=headers)
    assert resp.status_code == 403


def test_superuser_can_get_other_user(client, auth_headers, make_user):
    headers, _ = auth_headers(email="admin@example.com", is_superuser=True)
    other = make_user(email="other@example.com")
    resp = client.get(f"{API}/{other.id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "other@example.com"


def test_get_user_requires_auth(client, make_user):
    user = make_user(email="noauth@example.com")
    resp = client.get(f"{API}/{user.id}")
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# PATCH /users/{id}
# --------------------------------------------------------------------------- #


def test_patch_own_email_ok(client, auth_headers):
    headers, user = auth_headers(email="patch@example.com")
    resp = client.patch(
        f"{API}/{user.id}",
        headers=headers,
        json={"email": "patched@example.com"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "patched@example.com"


def test_patch_other_user_forbidden(client, auth_headers, make_user):
    headers, _ = auth_headers(email="patcher@example.com")
    victim = make_user(email="patchvictim@example.com")
    resp = client.patch(
        f"{API}/{victim.id}",
        headers=headers,
        json={"email": "hacked@example.com"},
    )
    assert resp.status_code == 403


def test_patch_weak_password_rejected(client, auth_headers):
    headers, user = auth_headers(email="pwpatch@example.com")
    resp = client.patch(
        f"{API}/{user.id}",
        headers=headers,
        json={"password": "weak"},
    )
    assert resp.status_code == 422


def test_patch_new_password_works_for_login(client, auth_headers):
    # Trocar a senha pelo PATCH deve permitir login com a nova senha.
    headers, user = auth_headers(email="pwchange@example.com")
    new_password = "BrandNewPass456!"
    patch = client.patch(
        f"{API}/{user.id}",
        headers=headers,
        json={"password": new_password},
    )
    assert patch.status_code == 200

    login = client.post(
        "/api/v1/auth/login",
        data={"username": "pwchange@example.com", "password": new_password},
    )
    assert login.status_code == 200
    # E a senha antiga não funciona mais
    old = client.post(
        "/api/v1/auth/login",
        data={"username": "pwchange@example.com", "password": TEST_PASSWORD},
    )
    assert old.status_code == 401
