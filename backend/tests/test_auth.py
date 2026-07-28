"""
Tests for the authentication flow: register, login, /me, refresh, and logout.

Cover the happy path and the main security rules:
- registration locked once a user already exists (single-operator / lockout)
- strong password policy
- refresh token rotation (the old one is blacklisted)
- logout invalidates the access token (blacklist)
"""
from tests.conftest import TEST_PASSWORD

API = "/api/v1/auth"


def _login(client, email: str, password: str = TEST_PASSWORD):
    """Helper: logs in via the OAuth2 form and returns the response."""
    return client.post(
        f"{API}/login",
        data={"username": email, "password": password},
    )


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


def test_register_first_user_succeeds(client):
    # With no users in the database, the first registration is allowed (initial setup).
    resp = client.post(
        f"{API}/register",
        json={"email": "first@example.com", "password": TEST_PASSWORD},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "first@example.com"
    assert "hashed_password" not in body  # never expose the hash


def test_first_user_is_promoted_to_superuser(client):
    """
    Bootstrap: the very first account on an empty platform becomes the superuser.

    Without it, a fresh install with DEMO_MODE=false has no way in — the demo
    superuser is only seeded in demo mode and every other account-creating route
    already requires an authenticated admin. Reachable exactly once: with
    REGISTRATION_ENABLED=false the endpoint refuses to serve once any user exists.
    """
    body = client.post(
        f"{API}/register",
        json={"email": "owner@example.com", "password": TEST_PASSWORD},
    ).json()

    assert body["is_superuser"] is True
    assert body["role"] == "admin"
    # A platform-level account belongs to no single company.
    assert body["company_id"] is None


def test_second_registration_is_not_a_superuser(client, monkeypatch):
    """
    Only the bootstrap account is privileged. With open registration the second
    signup is an ordinary member — and, having no company, it is scoped to
    nothing (see test_scoping.py).
    """
    from src.core.config import settings

    monkeypatch.setattr(settings, "REGISTRATION_ENABLED", True)
    client.post(
        f"{API}/register",
        json={"email": "owner@example.com", "password": TEST_PASSWORD},
    )
    body = client.post(
        f"{API}/register",
        json={"email": "joiner@example.com", "password": TEST_PASSWORD},
    ).json()

    assert body["is_superuser"] is False
    assert body["role"] == "member"
    assert body["company_id"] is None


def test_register_blocked_when_users_exist(client, make_user):
    # With a user already existing and REGISTRATION_ENABLED=false, new registrations get 403.
    make_user(email="existing@example.com")
    resp = client.post(
        f"{API}/register",
        json={"email": "second@example.com", "password": TEST_PASSWORD},
    )
    assert resp.status_code == 403


def test_register_weak_password_rejected(client):
    # A short/weak password is blocked by the schema's validator (422).
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
# HttpOnly cookies (frontend uses cookies; the Authorization header takes precedence)
# --------------------------------------------------------------------------- #


def test_login_sets_httponly_cookies(client, make_user):
    make_user(email="cookie@example.com")
    resp = _login(client, "cookie@example.com")
    assert resp.status_code == 200

    set_cookies = resp.headers.get_list("set-cookie")
    access = next((c for c in set_cookies if c.startswith("access_token=")), None)
    refresh = next((c for c in set_cookies if c.startswith("refresh_token=")), None)
    assert access is not None and refresh is not None
    for cookie in (access, refresh):
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie


def test_me_authenticates_via_cookie_only(client, make_user):
    # Without an Authorization header: the cookie written at login is enough for /me.
    make_user(email="cookie-me@example.com")
    _login(client, "cookie-me@example.com")

    resp = client.get(f"{API}/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "cookie-me@example.com"


def test_refresh_via_cookie_rotates_tokens(client, make_user):
    make_user(email="cookie-refresh@example.com")
    old_refresh = _login(client, "cookie-refresh@example.com").json()["refresh_token"]

    # No header or body: the refresh_token comes from the cookie.
    resp = client.post(f"{API}/refresh")
    assert resp.status_code == 200
    assert resp.json()["access_token"]

    # Rotation also applies to the cookie flow: the old refresh token was blacklisted.
    reuse = client.post(
        f"{API}/refresh",
        headers={"Authorization": f"Bearer {old_refresh}"},
    )
    assert reuse.status_code == 401


def test_logout_clears_cookies(client, make_user):
    make_user(email="cookie-logout@example.com")
    _login(client, "cookie-logout@example.com")

    resp = client.post(f"{API}/logout")
    assert resp.status_code == 200

    # Cookies cleared in the response (Max-Age=0) and the session dead for the client.
    set_cookies = resp.headers.get_list("set-cookie")
    cleared = [c.split("=", 1)[0] for c in set_cookies if 'Max-Age=0' in c]
    assert "access_token" in cleared
    assert "refresh_token" in cleared
    assert client.get(f"{API}/me").status_code == 401


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
    # Rotation: using the refresh token once should invalidate it for reuse.
    make_user(email="rotate@example.com")
    refresh_token = _login(client, "rotate@example.com").json()["refresh_token"]

    first = client.post(
        f"{API}/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert first.status_code == 200

    # Reusing the SAME refresh token should now fail (already blacklisted).
    second = client.post(
        f"{API}/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert second.status_code == 401


def test_access_token_rejected_on_refresh_endpoint(client, auth_headers):
    # The /refresh endpoint requires a "refresh"-type token, not "access".
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

    # /me works before logout
    assert client.get(f"{API}/me", headers=headers).status_code == 200

    logout = client.post(f"{API}/logout", headers=headers)
    assert logout.status_code == 200

    # After logout, the same access token is blacklisted → 401
    assert client.get(f"{API}/me", headers=headers).status_code == 401
