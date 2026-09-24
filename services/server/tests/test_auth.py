"""Login and token-verification behaviour."""


def test_login_success_returns_token(client, user_factory):
    user_factory("alice", "pass123")
    resp = client.post("/users/login", data={"username": "alice", "password": "pass123"})
    assert resp.status_code == 200
    assert resp.get_json(force=True)["response"]["token"]


def test_login_wrong_password(client, user_factory):
    user_factory("alice", "pass123")
    resp = client.post("/users/login", data={"username": "alice", "password": "nope"})
    assert resp.status_code == 404


def test_login_unknown_user(client, user_factory):
    resp = client.post("/users/login", data={"username": "ghost", "password": "x"})
    assert resp.status_code == 404
    # same answer as a wrong password (and the same hash check behind it), so
    # neither the body nor the timing says whether the username exists
    user_factory("alice", "pass123")
    wrong = client.post("/users/login", data={"username": "alice", "password": "x"})
    assert wrong.status_code == 404 and wrong.data == resp.data


def test_login_missing_password(client, user_factory):
    user_factory("alice")
    resp = client.post("/users/login", data={"username": "alice"})
    assert resp.status_code == 400


def test_protected_route_requires_token(client):
    resp = client.post(
        "/jobs/update/stats",
        data={"job_id": "j", "statistics_for_students": "true"},
    )
    assert resp.status_code == 401


def test_protected_route_rejects_invalid_token(client, user_factory):
    user_factory("alice")
    resp = client.post(
        "/jobs/update/stats",
        data={
            "user_id": "alice",
            "token": "not-a-real-token",
            "job_id": "j",
            "statistics_for_students": "true",
        },
    )
    assert resp.status_code == 401


def test_invalid_token_response_is_flagged_for_the_client(client, user_factory):
    user_factory("alice")
    resp = client.post("/jobs", data={"user_id": "alice", "token": "nope"})
    assert resp.status_code == 401
    assert resp.get_json(force=True)["code"] == "token_invalid"


def test_token_must_match_claimed_user(client, user_factory, login):
    user_factory("alice")
    user_factory("bob")
    alice_token = login("alice")
    # present alice's token but claim to be bob -> rejected
    resp = client.post(
        "/jobs/update/stats",
        data={
            "user_id": "bob",
            "token": alice_token,
            "job_id": "j",
            "statistics_for_students": "true",
        },
    )
    assert resp.status_code == 401


# ------------------------------------------------------------ token expiry ----
def _age_token(app_module_fixture, token, days):
    """Backdate a token's creation_time by ``days`` (naive, like pymongo)."""
    import datetime as dt

    created = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    app_module_fixture.mongo["RMN"]["tokens"].update_one(
        {"token": token}, {"$set": {"creation_time": created.replace(tzinfo=None)}}
    )


def test_fresh_token_accepted(client, user_factory, login, app_module_fixture):
    user_factory("alice")
    token = login("alice")
    _age_token(app_module_fixture, token, days=1)
    resp = client.post(
        "/jobs/update/stats",
        data={"user_id": "alice", "token": token, "job_id": "j",
              "statistics_for_students": "true"},
    )
    assert resp.status_code != 401


def test_expired_token_rejected_and_deleted(
    client, user_factory, login, app_module_fixture
):
    from service import user_service

    user_factory("alice")
    token = login("alice")
    _age_token(app_module_fixture, token, days=user_service.TOKEN_TTL_DAYS + 1)
    resp = client.post(
        "/jobs/update/stats",
        data={"user_id": "alice", "token": token, "job_id": "j",
              "statistics_for_students": "true"},
    )
    assert resp.status_code == 401
    assert app_module_fixture.mongo["RMN"]["tokens"].find_one({"token": token}) is None


def test_token_without_timestamp_rejected(client, user_factory, app_module_fixture):
    user_factory("alice")
    app_module_fixture.mongo["RMN"]["tokens"].insert_one(
        {"token": "legacy", "username": "alice", "role": "Utilisateur"}
    )
    resp = client.post(
        "/jobs/update/stats",
        data={"user_id": "alice", "token": "legacy", "job_id": "j",
              "statistics_for_students": "true"},
    )
    assert resp.status_code == 401


def test_ttl_index_created_at_startup(app_module_fixture):
    from service import user_service

    info = app_module_fixture.mongo["RMN"]["tokens"].index_information()
    assert "creation_time_ttl" in info
    assert info["creation_time_ttl"]["expireAfterSeconds"] == (
        user_service.TOKEN_TTL_DAYS * 86400
    )


def test_ttl_index_recreated_when_ttl_changes(app_module_fixture, monkeypatch):
    from service import user_service

    db = app_module_fixture.mongo["RMN"]
    monkeypatch.setattr(user_service, "TOKEN_TTL_DAYS", 7)
    user_service.UserService.ensure_token_expiration(db)
    assert db["tokens"].index_information()["creation_time_ttl"][
        "expireAfterSeconds"
    ] == 7 * 86400
    monkeypatch.setattr(user_service, "TOKEN_TTL_DAYS", 0)
    user_service.UserService.ensure_token_expiration(db)
    assert "creation_time_ttl" not in db["tokens"].index_information()
    # restore the default index for the other tests
    monkeypatch.undo()
    user_service.UserService.ensure_token_expiration(db)


def test_delete_tokens_by_age_handles_naive_timestamps(
    user_factory, login, app_module_fixture
):
    from service.user_service import UserService

    user_factory("alice")
    old, new = login("alice"), login("alice")
    _age_token(app_module_fixture, old, days=3)
    UserService.delete_tokens("alice", 2, app_module_fixture.mongo["RMN"])
    tokens = {t["token"] for t in app_module_fixture.mongo["RMN"]["tokens"].find()}
    assert tokens == {new}


# -------------------------------------------------------- response hardening ----
def test_security_headers_on_every_response(client):
    resp = client.get("/")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"


def test_request_body_cap_returns_413(client, app_module_fixture, monkeypatch):
    app = app_module_fixture.app
    assert app.config["MAX_CONTENT_LENGTH"] == 5 * 1024**3  # default 5 GiB
    monkeypatch.setitem(app.config, "MAX_CONTENT_LENGTH", 1024)
    resp = client.post("/users/login", data={"username": "a", "password": "x" * 4096})
    assert resp.status_code == 413
    assert resp.mimetype == "application/json"
    assert resp.get_json()["response"].startswith("Error")


def test_token_lookup_index_exists(app_module_fixture):
    # every token check (server and socketIO handshakes) looks a token up
    info = app_module_fixture.mongo["RMN"]["tokens"].index_information()
    assert info["token_lookup"]["key"] == [("token", 1)]


def test_username_field_is_checked_even_with_user_id(client, user_factory, login):
    # bob's token and user_id with alice's username used to pass: the username
    # clause was skipped whenever user_id was present, and the profile
    # handlers then updated the user named by the form
    user_factory("alice")
    user_factory("bob")
    token = login("bob")
    resp = client.put(
        "/users/updateSaveVerifiedImages",
        data={"user_id": "bob", "username": "alice", "token": token, "saveVerifiedImages": "1"},
    )
    assert resp.status_code == 401
    assert resp.get_json(force=True)["code"] == "token_invalid"
