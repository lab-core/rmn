"""Operator endpoints behind the admin key: users, tokens, passwords, sweeps."""

import datetime as dt
import os

HEADERS = {"X-Admin-Key": "test-admin-key"}


def test_admin_users_lists_everyone(client, user_factory):
    user_factory("alice")
    user_factory("bob")
    resp = client.post("/admin/users", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.get_json(force=True)
    assert body["response"] == "OK" and sorted(body["users"]) == ["alice", "bob"]


def test_admin_delete_user_removes_everything_they_own(
    client, user_factory, job_factory, login, app_module_fixture
):
    mongo = app_module_fixture.mongo["RMN"]
    storage = app_module_fixture.storage
    user_factory("alice")
    user_factory("bob")
    login("alice")
    job_factory("j-alice", "alice", queued_time=dt.datetime.now(dt.UTC))
    job_factory("j-bob", "bob", queued_time=dt.datetime.now(dt.UTC))
    mongo["template"].insert_many(
        [
            {"template_id": "t1", "user_id": "alice", "template_file_id": "templates/t1.pdf", "locked": False},
            {"template_id": "t2", "user_id": "bob", "template_file_id": "templates/t2.pdf", "locked": False},
        ]
    )
    for rel in ("templates/t1.pdf", "templates/t2.pdf"):
        path = storage.abs_path(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()

    resp = client.post("/admin/delete/user", data={"username": "alice"}, headers=HEADERS)

    assert resp.status_code == 200
    assert [u["username"] for u in mongo["users"].find()] == ["bob"]
    assert mongo["tokens"].count_documents({"username": "alice"}) == 0
    assert [j["job_id"] for j in mongo["eval_jobs"].find()] == ["j-bob"]
    assert [t["template_id"] for t in mongo["template"].find()] == ["t2"]
    assert not os.path.exists(storage.abs_path("templates/t1.pdf"))
    assert os.path.exists(storage.abs_path("templates/t2.pdf"))
    os.remove(storage.abs_path("templates/t2.pdf"))

    assert client.post("/admin/delete/user", data={}, headers=HEADERS).status_code == 400


def test_admin_change_password_needs_no_old_password(client, user_factory, login):
    user_factory("alice", password="pass123")
    resp = client.post(
        "/admin/change_password", data={"username": "alice", "new_password": "Reset123"}, headers=HEADERS
    )
    assert resp.status_code == 200
    login("alice", "Reset123")
    assert client.post("/users/login", data={"username": "alice", "password": "pass123"}).status_code == 404


def test_admin_delete_tokens(client, user_factory, login, app_module_fixture):
    mongo = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    user_factory("bob")
    login("alice")
    login("alice")
    login("bob")

    assert client.post("/admin/delete/tokens", data={"username": "alice"}, headers=HEADERS).status_code == 200
    assert [t["username"] for t in mongo["tokens"].find()] == ["bob"]
    assert client.post("/admin/delete/tokens", data={}, headers=HEADERS).status_code == 200
    assert mongo["tokens"].count_documents({}) == 0


def test_admin_delete_jobs_reports_the_count(client, job_factory, app_module_fixture):
    now = dt.datetime.now(dt.UTC)
    job_factory("old", "alice", queued_time=now - dt.timedelta(days=100))
    job_factory("new", "alice", queued_time=now)

    resp = client.post("/admin/delete/jobs", data={"n_days_old": "30"}, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.get_json(force=True)["n_deleted_jobs"] == 1
    assert [j["job_id"] for j in app_module_fixture.mongo["RMN"]["eval_jobs"].find()] == ["new"]
    assert client.post("/admin/delete/jobs", data={}, headers=HEADERS).status_code == 400


def test_admin_executor_wakes_a_worker(client, app_module_fixture):
    assert client.get("/admin/executor", headers=HEADERS).status_code == 200
    assert app_module_fixture.redis.lrange("job_queue", 0, -1) == [b"{}"]


def test_admin_delete_jobs_refuses_a_malformed_or_negative_age(client, job_factory, app_module_fixture):
    job_factory("new", "alice", queued_time=dt.datetime.now(dt.UTC))
    for value, message in (("x", "Error: n_days_old is not a number."), ("-1", "Error: n_days_old must be >= 0.")):
        resp = client.post("/admin/delete/jobs", data={"n_days_old": value}, headers=HEADERS)
        assert resp.status_code == 400, value
        assert resp.get_json(force=True) == {"response": message}
    # a negative age put the cutoff in the future: the new job would have gone
    assert app_module_fixture.mongo["RMN"]["eval_jobs"].count_documents({}) == 1


def test_admin_delete_tokens_refuses_a_malformed_or_negative_age(client, user_factory, login, app_module_fixture):
    user_factory("alice")
    login("alice")
    for value in ("x", "-3"):
        resp = client.post("/admin/delete/tokens", data={"n_days_old": value}, headers=HEADERS)
        assert resp.status_code == 400, value
    assert app_module_fixture.mongo["RMN"]["tokens"].count_documents({}) == 1


def test_admin_storage_clean_refuses_an_age_that_is_not_finite(client):
    for value in ("nan", "inf", "x"):
        resp = client.post("/admin/storage/clean", data={"min_age_hours": value}, headers=HEADERS)
        assert resp.status_code == 400, value
        assert resp.get_json(force=True) == {"response": "Error: min_age_hours is not a number."}
