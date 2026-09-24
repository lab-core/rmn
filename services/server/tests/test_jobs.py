"""Job listing, lookup, sharing, status changes and the age-based sweep."""

import datetime as dt
import json
import os
from service import job_cleanup


def _now():
    return dt.datetime.now(dt.UTC)


def _auth(token, user="alice", **extra):
    return {"user_id": user, "token": token, **extra}


def _queue(app_module):
    return [json.loads(p) for p in app_module.redis.lrange("job_queue", 0, -1)]


def test_jobs_lists_the_callers_jobs_and_requeues_dead_runs(
    client, user_factory, job_factory, login, app_module_fixture
):
    user_factory("alice")
    user_factory("bob")
    token = login("alice")
    stale = _now() - dt.timedelta(seconds=600)
    job_factory("j-dead", "alice", status="RUN", queued_time=_now(), alive_time=stale, retry=0)
    job_factory("j-live", "alice", status="RUN", queued_time=_now(), alive_time=_now())
    job_factory("j-ok", "alice", status="VALIDATION", queued_time=_now(), job_infos="fine")
    job_factory("j-bob", "bob", status="VALIDATION", queued_time=_now())

    resp = client.post("/jobs", data=_auth(token))

    assert resp.status_code == 200
    jobs = {j["job_id"]: j for j in resp.get_json(force=True)["response"]}
    assert sorted(jobs) == ["j-dead", "j-live", "j-ok"]
    assert jobs["j-ok"]["job_infos"] == "fine" and jobs["j-ok"]["job_name"] == "test job"

    eval_jobs = app_module_fixture.mongo["RMN"]["eval_jobs"]
    dead = eval_jobs.find_one({"job_id": "j-dead"})
    assert dead["job_status"] == "QUEUED" and dead["retry"] == 1
    assert eval_jobs.find_one({"job_id": "j-live"})["job_status"] == "RUN"
    assert _queue(app_module_fixture) == [{"job_id": "j-dead"}]


def test_job_returns_the_full_record_to_its_owner(client, user_factory, job_factory, login):
    user_factory("alice")
    token = login("alice")
    job_factory(
        "j1", "alice", queued_time=_now(), statistics_for_students=True,
        n_pages_per_question=[["Q1", 2]], groups=["A", "B"], copies_errors=["x.pdf"],
    )

    resp = client.post("/job", data=_auth(token, job_id="j1"))

    assert resp.status_code == 200
    job = resp.get_json(force=True)["response"]
    assert job["job_id"] == "j1"
    assert job["n_pages_per_question"] == [["Q1", 2]]
    assert job["groups"] == ["A", "B"]
    assert job["copies_errors"] == ["x.pdf"]
    assert job["statistics_for_students"] is True


def test_job_is_readable_with_a_share_token_only(client, job_factory):
    job_factory("j1", "alice", queued_time=_now(), statistics_for_students=False,
                share_token={"questions": "s1"})
    assert client.post("/job", data={"job_id": "j1", "share_token": "s1"}).status_code == 200
    assert client.post("/job", data={"job_id": "j1", "share_token": "wrong"}).status_code == 401
    assert client.post("/job", data={"share_token": "s1"}).status_code == 401


def test_job_of_another_user_is_refused(client, user_factory, job_factory, login):
    user_factory("alice")
    user_factory("bob")
    job_factory("j1", "alice", queued_time=_now())
    token = login("bob")
    assert client.post("/job", data=_auth(token, user="bob", job_id="j1")).status_code == 401
    assert client.post("/job", data=_auth(token, user="bob", job_id="nope")).status_code == 401


def test_share_job_creates_one_token_per_scope(client, user_factory, job_factory, login, app_module_fixture):
    user_factory("alice")
    token = login("alice")
    job_factory("j1", "alice", queued_time=_now())
    headers = {"Host": "rmn.example.ca"}

    resp = client.post("/job/share", data=_auth(token, job_id="j1"), headers=headers)
    assert resp.status_code == 200
    url = resp.get_json(force=True)["response"]["share_url"]
    job = app_module_fixture.mongo["RMN"]["eval_jobs"].find_one({"job_id": "j1"})
    questions_token = job["share_token"]["questions"]
    assert url == f"https://rmn.example.ca/task-validation/?job_id=j1&token={questions_token}"

    # same scope again: same token
    resp = client.post("/job/share", data=_auth(token, job_id="j1"), headers=headers)
    assert resp.get_json(force=True)["response"]["share_url"] == url

    resp = client.post("/job/share", data=_auth(token, job_id="j1", all="1"), headers=headers)
    url = resp.get_json(force=True)["response"]["share_url"]
    job = app_module_fixture.mongo["RMN"]["eval_jobs"].find_one({"job_id": "j1"})
    assert url == f"https://rmn.example.ca/dashboard/?job_id=j1&token={job['share_token']['all']}"

    resp = client.post("/job/share", data=_auth(token, job_id="j1", question_index="Q2"), headers=headers)
    url = resp.get_json(force=True)["response"]["share_url"]
    job = app_module_fixture.mongo["RMN"]["eval_jobs"].find_one({"job_id": "j1"})
    assert url.endswith(f"&token={job['share_token']['Q2']}&question_index=Q2")
    assert len({questions_token, job["share_token"]["all"], job["share_token"]["Q2"]}) == 3

    # localhost is served over http
    resp = client.post("/job/share", data=_auth(token, job_id="j1"), headers={"Host": "localhost"})
    assert resp.get_json(force=True)["response"]["share_url"].startswith("http://localhost/")


def test_share_job_errors(client, user_factory, job_factory, login):
    user_factory("alice")
    user_factory("bob")
    token = login("bob")
    job_factory("j1", "alice", queued_time=_now())
    assert client.post("/job/share", data=_auth(token, user="bob", job_id="j1")).status_code == 404
    assert client.post("/job/share", data=_auth(token, user="bob")).status_code == 400


def test_unshare_removes_one_scope_at_a_time(client, user_factory, job_factory, login, app_module_fixture):
    user_factory("alice")
    user_factory("bob")
    token = login("alice")
    job_factory("j1", "alice", queued_time=_now(), share_token={"questions": "a", "all": "b", "Q2": "c"})
    eval_jobs = app_module_fixture.mongo["RMN"]["eval_jobs"]

    assert client.post("/job/unshare", data=_auth(token, job_id="j1")).status_code == 200
    assert eval_jobs.find_one({"job_id": "j1"})["share_token"] == {"all": "b", "Q2": "c"}
    assert client.post("/job/unshare", data=_auth(token, job_id="j1", question_index="Q2")).status_code == 200
    assert client.post("/job/unshare", data=_auth(token, job_id="j1", all="1")).status_code == 200
    assert eval_jobs.find_one({"job_id": "j1"})["share_token"] == {}

    bob = login("bob")
    assert client.post("/job/unshare", data=_auth(bob, user="bob", job_id="j1")).status_code == 404
    assert client.post("/job/unshare", data=_auth(token)).status_code == 400


def test_status_update_validates_the_status(client, user_factory, job_factory, login, app_module_fixture):
    user_factory("alice")
    token = login("alice")
    job_factory("j1", "alice", status="VALIDATION")

    resp = client.post("/job/update/status", data=_auth(token, job_id="j1", job_status="nonsense"))
    assert resp.status_code == 400
    resp = client.post("/job/update/status", data=_auth(token, job_id="j1", job_status="archived"))
    assert resp.status_code == 200
    assert app_module_fixture.mongo["RMN"]["eval_jobs"].find_one({"job_id": "j1"})["job_status"] == "ARCHIVED"
    assert client.post("/job/update/status", data=_auth(token, job_id="j1")).status_code == 400


def test_stats_and_bonus_updates_are_stored(client, user_factory, job_factory, login, app_module_fixture):
    user_factory("alice")
    token = login("alice")
    job_factory("j1", "alice")
    eval_jobs = app_module_fixture.mongo["RMN"]["eval_jobs"]

    client.post("/job/update/stats", data=_auth(token, job_id="j1", statistics_for_students="True"))
    assert eval_jobs.find_one({"job_id": "j1"})["statistics_for_students"] is True
    client.post("/job/update/stats", data=_auth(token, job_id="j1", statistics_for_students="false"))
    assert eval_jobs.find_one({"job_id": "j1"})["statistics_for_students"] is False

    client.post("/job/update/bonus", data=_auth(token, job_id="j1", bonus_enabled_map='[["Q1", true]]'))
    assert eval_jobs.find_one({"job_id": "j1"})["bonus_enabled_map"] == [["Q1", True]]
    assert client.post("/job/update/bonus", data=_auth(token, job_id="j1")).status_code == 400


def test_ignore_resets_a_retry_job_and_requeues_it(
    client, user_factory, job_factory, login, app_module_fixture
):
    user_factory("alice")
    token = login("alice")
    job_factory("j1", "alice", status="RETRY", copies_errors=["bad.pdf"], job_infos="1 copie invalide")
    storage = app_module_fixture.storage
    bad = os.path.join(storage.abs_path(os.path.join("incorrect_files", "j1")), "bad.pdf")
    os.makedirs(os.path.dirname(bad), exist_ok=True)
    open(bad, "w").close()

    resp = client.post("/job/ignore", data=_auth(token, job_id="j1"))

    assert resp.status_code == 200
    job = app_module_fixture.mongo["RMN"]["eval_jobs"].find_one({"job_id": "j1"})
    assert job["job_status"] == "IGNORED"
    assert "copies_errors" not in job and "job_infos" not in job
    assert not os.path.exists(os.path.dirname(bad))
    assert _queue(app_module_fixture) == [{"job_id": "j1"}]


def test_ignore_keeps_the_status_of_a_job_that_is_not_retrying(
    client, user_factory, job_factory, login, app_module_fixture
):
    user_factory("alice")
    token = login("alice")
    job_factory("j1", "alice", status="VALIDATION", job_infos="note")
    assert client.post("/job/ignore", data=_auth(token, job_id="j1")).status_code == 200
    job = app_module_fixture.mongo["RMN"]["eval_jobs"].find_one({"job_id": "j1"})
    assert job["job_status"] == "VALIDATION" and "job_infos" not in job


def test_delete_old_jobs_sweeps_by_age_and_owner(app_module_fixture, job_factory):
    mongo = app_module_fixture.mongo["RMN"]
    job_factory("old-a", "alice", queued_time=_now() - dt.timedelta(days=40))
    job_factory("old-b", "bob", queued_time=_now() - dt.timedelta(days=40))
    job_factory("new-a", "alice", queued_time=_now())
    for job_id in ("old-a", "old-b", "new-a"):
        mongo["job_documents"].insert_one({"job_id": job_id})
        mongo["versions"].insert_one({"job_id": job_id})
    storage = app_module_fixture.storage
    csv = storage.abs_path(os.path.join("csv", "old-a.csv"))
    os.makedirs(os.path.dirname(csv), exist_ok=True)
    open(csv, "w").close()
    app_module_fixture.redis.lpush("job_queue", json.dumps({"job_id": "old-a"}))

    assert job_cleanup.delete_old_jobs(30, user_id="alice") == 1

    assert sorted(j["job_id"] for j in mongo["eval_jobs"].find()) == ["new-a", "old-b"]
    assert mongo["job_documents"].count_documents({"job_id": "old-a"}) == 0
    assert mongo["versions"].count_documents({"job_id": "old-a"}) == 0
    assert not os.path.exists(csv)
    assert _queue(app_module_fixture) == []

    assert job_cleanup.delete_old_jobs(0) == 2
    assert mongo["eval_jobs"].count_documents({}) == 0


def test_documents_serves_the_matricule_confidence(client, app_module_fixture, login, user_factory, job_factory):
    mongo = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    token = login("alice")
    job_factory("j-mat", "alice")
    base = {"job_id": "j-mat", "grades": [], "filename": "copy", "status": "VALIDATED", "execution_time": 1}
    mongo["job_documents"].insert_many([
        {**base, "document_index": 0, "matricule": "2345678", "matricule_confidence": 0.73},
        # read before the confidence was stored
        {**base, "document_index": 1, "matricule": "2345679"},
    ])

    resp = client.post("/documents", data={"job_id": "j-mat", "token": token})

    assert resp.status_code == 200
    docs = sorted(resp.get_json(force=True)["response"], key=lambda d: d["document_index"])
    assert [d["matricule_confidence"] for d in docs] == [0.73, None]
