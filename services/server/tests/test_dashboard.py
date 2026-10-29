"""What the webapp's admin page calls: account actions and operator commands."""

import datetime as dt

import pytest

ADMIN = "Administrateur"
MANAGER = "Gestionnaire"
USER = "Utilisateur"


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def db(app_module_fixture):
    return app_module_fixture.mongo["RMN"]


@pytest.fixture
def admin(user_factory, login):
    user_factory("root", role=ADMIN)
    return login("root")


def _post(client, path, token, caller="root", **data):
    return client.post(path, data={"user_id": caller, **data}, headers=_auth(token))


def test_the_list_shows_last_login_and_task_count(
    client, admin, user_factory, job_factory, login
):
    user_factory("alice")
    user_factory("bob")
    job_factory("j1", "alice", queued_time=dt.datetime.now(dt.UTC))
    job_factory("j2", "alice", queued_time=dt.datetime.now(dt.UTC))
    login("alice")

    rows = client.get("/users/all", headers=_auth(admin)).get_json(force=True)[
        "response"
    ]
    by_name = {r["username"]: r for r in rows}
    assert by_name["alice"]["tasks"] == 2 and by_name["bob"]["tasks"] == 0
    assert by_name["alice"]["lastLogin"] is not None
    assert by_name["bob"]["lastLogin"] is None


def test_an_admin_changes_a_role_and_the_sessions_close(
    client, admin, user_factory, login, db
):
    user_factory("alice")
    session = login("alice")
    resp = _post(client, "/users/role", admin, username="alice", role=MANAGER)
    assert resp.status_code == 200
    assert db["users"].find_one({"username": "alice"})["role"] == MANAGER
    assert db["tokens"].find_one({"token": session}) is None

    assert (
        _post(client, "/users/role", admin, username="alice", role="Boss").status_code
        == 400
    )
    assert (
        _post(client, "/users/role", admin, username="nobody", role=USER).status_code
        == 404
    )
    # never their own: the last admin would lock everyone out
    assert (
        _post(client, "/users/role", admin, username="root", role=USER).status_code
        == 400
    )


def test_a_manager_changes_no_role(client, user_factory, login):
    user_factory("chef", role=MANAGER)
    user_factory("alice")
    token = login("chef")
    resp = _post(
        client, "/users/role", token, caller="chef", username="alice", role=MANAGER
    )
    assert resp.status_code == 403


def test_an_admin_closes_the_sessions_of_a_user(client, admin, user_factory, login, db):
    user_factory("alice")
    login("alice")
    login("alice")
    assert (
        _post(client, "/users/sessions/close", admin, username="alice").status_code
        == 200
    )
    assert db["tokens"].count_documents({"username": "alice"}) == 0
    assert db["tokens"].count_documents({"username": "root"}) == 1
    assert (
        _post(client, "/users/sessions/close", admin, username="nobody").status_code
        == 404
    )


def test_an_admin_deletes_an_account_with_its_jobs(
    client, admin, user_factory, job_factory, login, db
):
    user_factory("chef", role=MANAGER)
    user_factory("alice")
    user_factory("bob")
    db["users"].update_one({"username": "bob"}, {"$set": {"managers": ["chef"]}})
    job_factory("j1", "alice", queued_time=dt.datetime.now(dt.UTC))
    login("alice")

    assert _post(client, "/users/delete", admin, username="alice").status_code == 200
    assert db["users"].find_one({"username": "alice"}) is None
    assert db["eval_jobs"].find_one({"job_id": "j1"}) is None
    assert db["tokens"].count_documents({"username": "alice"}) == 0

    # a deleted Gestionnaire leaves the lists it was on
    assert _post(client, "/users/delete", admin, username="chef").status_code == 200
    assert db["users"].find_one({"username": "bob"})["managers"] == []

    assert _post(client, "/users/delete", admin, username="root").status_code == 400
    assert _post(client, "/users/delete", admin, username="nobody").status_code == 404


def test_a_manager_deletes_nobody(client, user_factory, login):
    user_factory("chef", role=MANAGER)
    user_factory("alice")
    resp = _post(
        client, "/users/delete", login("chef"), caller="chef", username="alice"
    )
    assert resp.status_code == 403


def test_the_operator_commands_need_an_admin(client, user_factory, login):
    user_factory("chef", role=MANAGER)
    token = login("chef")
    assert client.get("/manage/status", headers=_auth(token)).status_code == 403
    for path in (
        "/manage/storage/clean",
        "/manage/delete/jobs",
        "/manage/delete/tokens",
        "/manage/executor",
    ):
        assert _post(client, path, token, caller="chef").status_code == 403, path


def test_status_and_executor(client, admin, app_module_fixture):
    app_module_fixture.redis.delete("job_queue")
    assert client.get("/manage/status", headers=_auth(admin)).get_json(force=True)[
        "response"
    ] == {"queue": 0}
    assert _post(client, "/manage/executor", admin).status_code == 200
    assert client.get("/manage/status", headers=_auth(admin)).get_json(force=True)[
        "response"
    ] == {"queue": 1}


def test_the_storage_sweep_reports_by_default(client, admin):
    resp = _post(client, "/manage/storage/clean", admin, usage="true")
    assert resp.status_code == 200
    body = resp.get_json(force=True)
    assert body["dry_run"] is True and "usage" in body and "orphans" in body


def test_the_job_sweep_ignores_the_admins_own_name(
    client, admin, user_factory, job_factory, db
):
    user_factory("alice")
    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=400)
    job_factory("old", "alice", queued_time=old)
    job_factory("new", "alice", queued_time=dt.datetime.now(dt.UTC))
    # the form's user_id is the admin: it must not narrow the sweep to their jobs
    resp = _post(client, "/manage/delete/jobs", admin, n_days_old="365")
    assert resp.get_json(force=True)["n_deleted_jobs"] == 1
    assert db["eval_jobs"].find_one({"job_id": "old"}) is None
    assert db["eval_jobs"].find_one({"job_id": "new"}) is not None
    assert _post(client, "/manage/delete/jobs", admin).status_code == 400


def test_the_token_sweep_keeps_recent_sessions(client, admin, user_factory, login, db):
    user_factory("alice")
    login("alice")
    db["tokens"].insert_one(
        {
            "token": "old",
            "username": "alice",
            "role": USER,
            "creation_time": dt.datetime.now(dt.UTC) - dt.timedelta(days=10),
        }
    )
    assert (
        _post(client, "/manage/delete/tokens", admin, n_days_old="0").status_code == 400
    )
    assert (
        _post(client, "/manage/delete/tokens", admin, n_days_old="7").status_code == 200
    )
    assert db["tokens"].find_one({"token": "old"}) is None
    assert db["tokens"].count_documents({}) == 2
