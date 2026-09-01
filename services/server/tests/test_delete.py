"""Integration tests for POST /job/delete."""

import os


def _seed_related(app_module, job_id):
    db = app_module.mongo["RMN"]
    db["job_documents"].insert_one({"job_id": job_id, "doc_index": 0})
    db["job_questions"].insert_one({"job_id": job_id, "question": "Q1"})
    db["jobs_output"].insert_one({"job_id": job_id})
    db["versions"].insert_one({"job_id": job_id, "version": 0})


def _seed_storage(app_module, job_id):
    doc = app_module.storage.abs_path(os.path.join("documents", job_id))
    os.makedirs(doc, exist_ok=True)
    with open(os.path.join(doc, "c.pdf"), "wb") as f:
        f.write(b"pdf")


def test_delete_removes_job_everywhere(client, user_factory, job_factory, login, app_module_fixture):
    user_factory("alice")
    job_factory("job1", owner="alice")
    _seed_related(app_module_fixture, "job1")
    _seed_storage(app_module_fixture, "job1")
    token = login("alice")

    resp = client.post("/job/delete", data={"user_id": "alice", "token": token, "job_id": "job1"})
    assert resp.status_code == 200

    db = app_module_fixture.mongo["RMN"]
    for coll in ("eval_jobs", "job_documents", "job_questions", "jobs_output", "versions"):
        assert db[coll].count_documents({"job_id": "job1"}) == 0
    assert not os.path.exists(app_module_fixture.storage.abs_path(os.path.join("documents", "job1")))


def test_delete_foreign_job_is_rejected(client, user_factory, job_factory, login, app_module_fixture):
    user_factory("alice")
    user_factory("bob")
    job_factory("job1", owner="alice")
    _seed_storage(app_module_fixture, "job1")
    bob_token = login("bob")

    resp = client.post("/job/delete", data={"user_id": "bob", "token": bob_token, "job_id": "job1"})
    assert resp.status_code == 404
    # alice's job and its storage are untouched
    db = app_module_fixture.mongo["RMN"]
    assert db["eval_jobs"].count_documents({"job_id": "job1"}) == 1
    assert os.path.exists(app_module_fixture.storage.abs_path(os.path.join("documents", "job1")))


def test_delete_unknown_job_returns_404(client, user_factory, login):
    user_factory("alice")
    token = login("alice")
    resp = client.post("/job/delete", data={"user_id": "alice", "token": token, "job_id": "nope"})
    assert resp.status_code == 404
