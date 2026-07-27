"""
Object-level authorization tests on /users/{id}.

Lock down the security fix: a user can only read/change their OWN record;
the superuser can read anyone's. Without this, any authenticated user
could access another's data via UUID (IDOR).
"""
from datetime import datetime, timedelta, timezone

from src.models.audit_log import AuditLog
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
    # IDOR regression: a regular user CANNOT read another user.
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
# GET /users — last_activity (aggregated from audit_logs)
# --------------------------------------------------------------------------- #


def test_list_users_includes_last_activity(client, auth_headers, make_user, db):
    headers, _ = auth_headers(email="su@example.com", is_superuser=True)
    active = make_user(email="active@example.com")
    make_user(email="quiet@example.com")  # no audit entries

    ts = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    db.add_all([
        AuditLog(
            user_id=active.id, action="login", resource_type="auth",
            timestamp=ts - timedelta(days=1),
        ),
        AuditLog(
            user_id=active.id, action="instance_created", resource_type="instance",
            timestamp=ts,  # most recent activity
        ),
    ])
    db.commit()

    resp = client.get(API, headers=headers)
    assert resp.status_code == 200
    by_email = {u["email"]: u for u in resp.json()}
    # MAX(timestamp) per user; a user with no audit entries → None.
    assert by_email["active@example.com"]["last_activity"].startswith("2026-06-01T12:00")
    assert by_email["quiet@example.com"]["last_activity"] is None


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


def test_patch_own_email_to_taken_email_rejected(client, auth_headers, make_user):
    # Regression: an email already in use used to raise IntegrityError on commit → 500.
    make_user(email="taken@example.com")
    headers, user = auth_headers(email="dupe@example.com")
    resp = client.patch(
        f"{API}/{user.id}",
        headers=headers,
        json={"email": "taken@example.com"},
    )
    assert resp.status_code == 400
    assert "already registered" in resp.json()["detail"]


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
    # Changing the password via PATCH should allow logging in with the new password.
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
    # And the old password no longer works
    old = client.post(
        "/api/v1/auth/login",
        data={"username": "pwchange@example.com", "password": TEST_PASSWORD},
    )
    assert old.status_code == 401
