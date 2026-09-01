"""Login and token-verification behaviour."""


def test_login_success_returns_token(client, user_factory):
    user_factory("alice", "pass123")
    resp = client.post("/login", data={"username": "alice", "password": "pass123"})
    assert resp.status_code == 200
    assert resp.get_json(force=True)["response"]["token"]


def test_login_wrong_password(client, user_factory):
    user_factory("alice", "pass123")
    resp = client.post("/login", data={"username": "alice", "password": "nope"})
    assert resp.status_code == 404


def test_login_unknown_user(client):
    resp = client.post("/login", data={"username": "ghost", "password": "x"})
    assert resp.status_code == 404


def test_login_missing_password(client, user_factory):
    user_factory("alice")
    resp = client.post("/login", data={"username": "alice"})
    assert resp.status_code == 400


def test_protected_route_requires_token(client):
    resp = client.post(
        "/job/update/stats",
        data={"job_id": "j", "statistics_for_students": "true"},
    )
    assert resp.status_code == 401


def test_protected_route_rejects_invalid_token(client, user_factory):
    user_factory("alice")
    resp = client.post(
        "/job/update/stats",
        data={
            "user_id": "alice",
            "token": "not-a-real-token",
            "job_id": "j",
            "statistics_for_students": "true",
        },
    )
    assert resp.status_code == 401


def test_token_must_match_claimed_user(client, user_factory, login):
    user_factory("alice")
    user_factory("bob")
    alice_token = login("alice")
    # present alice's token but claim to be bob -> rejected
    resp = client.post(
        "/job/update/stats",
        data={
            "user_id": "bob",
            "token": alice_token,
            "job_id": "j",
            "statistics_for_students": "true",
        },
    )
    assert resp.status_code == 401
