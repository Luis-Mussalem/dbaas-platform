"""
Testes do fluxo de autenticação: registro, login, /me, refresh e logout.

Cobrem o caminho feliz e as regras de segurança principais:
- registro travado quando já existe usuário (single-operator / lockout)
- política de senha forte
- rotação de refresh token (o antigo é blacklistado)
- logout invalida o access token (blacklist)
"""
from tests.conftest import TEST_PASSWORD

API = "/api/v1/auth"


def _login(client, email: str, password: str = TEST_PASSWORD):
    """Helper: faz login via OAuth2 form e retorna a resposta."""
    return client.post(
        f"{API}/login",
        data={"username": email, "password": password},
    )


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #


def test_register_first_user_succeeds(client):
    # Sem usuários no banco, o primeiro registro é permitido (setup inicial).
    resp = client.post(
        f"{API}/register",
        json={"email": "first@example.com", "password": TEST_PASSWORD},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "first@example.com"
    assert "hashed_password" not in body  # nunca expor o hash


def test_register_blocked_when_users_exist(client, make_user):
    # Já existindo um usuário e REGISTRATION_ENABLED=false, novos registros 403.
    make_user(email="existing@example.com")
    resp = client.post(
        f"{API}/register",
        json={"email": "second@example.com", "password": TEST_PASSWORD},
    )
    assert resp.status_code == 403


def test_register_weak_password_rejected(client):
    # Senha curta/fraca é barrada pelo validador do schema (422).
    resp = client.post(
        f"{API}/register",
        json={"email": "weak@example.com", "password": "weak"},
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #


def test_login_success_returns_tokens(client, make_user):
    make_user(email="login@example.com")
    resp = _login(client, "login@example.com")
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


def test_login_wrong_password_401(client, make_user):
    make_user(email="login@example.com")
    resp = _login(client, "login@example.com", password="WrongPass123!")
    assert resp.status_code == 401


def test_login_unknown_email_401(client):
    resp = _login(client, "ghost@example.com")
    assert resp.status_code == 401


def test_inactive_user_cannot_login(client, make_user):
    make_user(email="inactive@example.com", is_active=False)
    resp = _login(client, "inactive@example.com")
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# /me
# --------------------------------------------------------------------------- #


def test_me_returns_current_user(client, auth_headers):
    headers, user = auth_headers(email="me@example.com")
    resp = client.get(f"{API}/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@example.com"


def test_me_requires_auth(client):
    resp = client.get(f"{API}/me")
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Refresh
# --------------------------------------------------------------------------- #


def test_refresh_returns_new_tokens(client, make_user):
    make_user(email="refresh@example.com")
    login = _login(client, "refresh@example.com")
    refresh_token = login.json()["refresh_token"]

    resp = client.post(
        f"{API}/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_old_refresh_token_is_blacklisted_after_use(client, make_user):
    # Rotação: usar o refresh token uma vez deve invalidá-lo para reuso.
    make_user(email="rotate@example.com")
    refresh_token = _login(client, "rotate@example.com").json()["refresh_token"]

    first = client.post(
        f"{API}/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert first.status_code == 200

    # Reusar o MESMO refresh token agora deve falhar (já está na blacklist).
    second = client.post(
        f"{API}/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert second.status_code == 401


def test_access_token_rejected_on_refresh_endpoint(client, auth_headers):
    # O endpoint /refresh exige um token do tipo "refresh", não "access".
    headers, _ = auth_headers(email="typecheck@example.com")
    resp = client.post(f"{API}/refresh", headers=headers)
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Logout
# --------------------------------------------------------------------------- #


def test_logout_blacklists_access_token(client, make_user):
    make_user(email="logout@example.com")
    tokens = _login(client, "logout@example.com").json()
    access = tokens["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    # /me funciona antes do logout
    assert client.get(f"{API}/me", headers=headers).status_code == 200

    logout = client.post(f"{API}/logout", headers=headers)
    assert logout.status_code == 200

    # Após o logout, o mesmo access token está blacklistado → 401
    assert client.get(f"{API}/me", headers=headers).status_code == 401
