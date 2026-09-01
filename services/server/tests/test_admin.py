"""Admin endpoints are guarded by the shared ADMIN_API_KEY secret."""

ADMIN_USERS = "/admin/users"


def test_admin_requires_key(client):
    assert client.post(ADMIN_USERS).status_code == 403


def test_admin_rejects_wrong_key(client):
    resp = client.post(ADMIN_USERS, headers={"X-Admin-Key": "wrong"})
    assert resp.status_code == 403


def test_admin_accepts_header_key(client, user_factory):
    user_factory("admin", "x", role="Administrateur")
    resp = client.post(ADMIN_USERS, headers={"X-Admin-Key": "test-admin-key"})
    assert resp.status_code == 200
    assert "admin" in resp.get_json(force=True)["users"]


def test_admin_accepts_form_key_fallback(client):
    resp = client.post(ADMIN_USERS, data={"admin_key": "test-admin-key"})
    assert resp.status_code == 200


def test_admin_fails_closed_when_secret_unset(client, monkeypatch, app_module_fixture):
    monkeypatch.setattr(app_module_fixture, "ADMIN_API_KEY", None)
    resp = client.post(ADMIN_USERS, headers={"X-Admin-Key": "test-admin-key"})
    assert resp.status_code == 403
    assert "disabled" in resp.get_json(force=True)["response"]


def test_admin_signup_creates_user(client, app_module_fixture):
    resp = client.post(
        "/admin/signup",
        headers={"X-Admin-Key": "test-admin-key"},
        data={"username": "newuser", "password": "pass123", "role": "Utilisateur"},
    )
    assert resp.status_code == 200
    assert app_module_fixture.mongo["RMN"]["users"].find_one({"username": "newuser"})


def test_admin_signup_blocked_without_key(client, app_module_fixture):
    resp = client.post(
        "/admin/signup",
        data={"username": "sneaky", "password": "pass123", "role": "Administrateur"},
    )
    assert resp.status_code == 403
    assert app_module_fixture.mongo["RMN"]["users"].find_one({"username": "sneaky"}) is None


def test_admin_executor_get_accepts_header_key(client):
    resp = client.get("/admin/executor", headers={"X-Admin-Key": "test-admin-key"})
    assert resp.status_code == 200


def test_admin_executor_get_rejected_without_key(client):
    assert client.get("/admin/executor").status_code == 403
