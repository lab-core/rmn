"""The login token in an Authorization header instead of the form body."""

import json


def _login(client, user_factory, username="alice"):
    user_factory(username)
    resp = client.post("/users/login", data={"username": username, "password": "pass123"})
    return json.loads(resp.data)["response"]["token"]


def test_bearer_header_authenticates_a_protected_route(client, user_factory):
    token = _login(client, user_factory)
    resp = client.post("/jobs", data={"user_id": "alice"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    # the form field is still accepted (older clients, scripts)
    assert client.post("/jobs", data={"user_id": "alice", "token": token}).status_code == 200
    # and the header alone is enough: no user_id or username needed in the body
    assert client.post("/jobs", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_header_wins_over_the_form_field(client, user_factory):
    token = _login(client, user_factory)
    resp = client.post(
        "/jobs", data={"user_id": "alice", "token": "stale"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    resp = client.post(
        "/jobs", data={"user_id": "alice", "token": token}, headers={"Authorization": "Bearer nope"}
    )
    assert resp.status_code == 401 and json.loads(resp.data)["code"] == "token_invalid"


def test_header_must_name_the_tokens_owner(client, user_factory):
    token = _login(client, user_factory)
    resp = client.post("/jobs", data={"user_id": "bob"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_other_schemes_and_empty_values_fall_back_to_the_form(client, user_factory):
    token = _login(client, user_factory)
    for header in ("Basic abc", "Bearer", "Bearer   ", "", "token " + token):
        resp = client.post(
            "/jobs", data={"user_id": "alice", "token": token}, headers={"Authorization": header}
        )
        assert resp.status_code == 200, header
        resp = client.post("/jobs", data={"user_id": "alice"}, headers={"Authorization": header})
        assert resp.status_code == 401, header


def test_share_token_routes_take_the_header_too(client, user_factory, app_module_fixture):
    token = _login(client, user_factory)
    app_module_fixture.mongo["RMN"]["eval_jobs"].insert_one({"job_id": "j1", "user_id": "alice"})
    resp = client.post(
        "/jobs/update/stats",
        data={"job_id": "j1", "statistics_for_students": "true"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code != 401
