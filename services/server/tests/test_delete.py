"""Integration tests for POST /job/delete.

The endpoint removes the job record synchronously and enqueues a delete task
on the Redis job_queue for an executor to drain; it does not clean storage
inline (unless the queue is unreachable).
"""

import json
import os
from routes import jobs as jobs_routes
from service import job_cleanup


def _queue(app_module):
    return [json.loads(x) for x in app_module.redis.lrange("job_queue", 0, -1)]


def _seed_related(app_module, job_id):
    db = app_module.mongo["RMN"]
    db["job_documents"].insert_one({"job_id": job_id, "doc_index": 0})
    db["versions"].insert_one({"job_id": job_id, "version": 0})


def _seed_storage(app_module, job_id):
    doc = app_module.storage.abs_path(os.path.join("documents", job_id))
    os.makedirs(doc, exist_ok=True)
    with open(os.path.join(doc, "c.pdf"), "wb") as f:
        f.write(b"pdf")


def test_delete_removes_record_and_enqueues_task(client, user_factory, job_factory, login, app_module_fixture):
    user_factory("alice")
    job_factory("job1", owner="alice")
    _seed_related(app_module_fixture, "job1")
    _seed_storage(app_module_fixture, "job1")
    token = login("alice")

    resp = client.post("/job/delete", data={"user_id": "alice", "token": token, "job_id": "job1"})
    assert resp.status_code == 200

    # the job record is gone synchronously
    assert app_module_fixture.mongo["RMN"]["eval_jobs"].count_documents({"job_id": "job1"}) == 0
    # a delete task was enqueued for the executor
    assert {"job_id": "job1", "delete": True} in _queue(app_module_fixture)
    # the heavy cleanup was NOT done inline (executor drains it later)
    assert app_module_fixture.mongo["RMN"]["job_documents"].count_documents({"job_id": "job1"}) == 1
    assert os.path.exists(app_module_fixture.storage.abs_path(os.path.join("documents", "job1")))


def test_delete_falls_back_to_background_thread_when_queue_unreachable(monkeypatch, client, user_factory, job_factory, login, app_module_fixture):
    user_factory("alice")
    job_factory("job1", owner="alice")
    _seed_related(app_module_fixture, "job1")
    _seed_storage(app_module_fixture, "job1")
    token = login("alice")

    def _boom(*a, **k):
        raise RuntimeError("redis down")

    monkeypatch.setattr(app_module_fixture.redis, "rpush", _boom)

    # capture the fallback thread and run its target synchronously
    spawned = []

    class _SyncThread:
        def __init__(self, target=None, args=(), **_):
            self._target, self._args = target, args

        def start(self):
            spawned.append((self._target, self._args))
            if self._target:
                self._target(*self._args)

    monkeypatch.setattr(jobs_routes, "Thread", _SyncThread)

    resp = client.post("/job/delete", data={"user_id": "alice", "token": token, "job_id": "job1"})
    assert resp.status_code == 200
    # queue was unreachable -> cleanup handed to a background thread (not inline,
    # not left undone); the record is still removed synchronously
    assert spawned and spawned[0][0] is job_cleanup.delete_job
    assert spawned[0][1] == ["job1"]
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
    # nothing enqueued, alice's job/storage intact
    assert _queue(app_module_fixture) == []
    assert app_module_fixture.mongo["RMN"]["eval_jobs"].count_documents({"job_id": "job1"}) == 1
    assert os.path.exists(app_module_fixture.storage.abs_path(os.path.join("documents", "job1")))


def test_delete_unknown_job_returns_404(client, user_factory, login, app_module_fixture):
    user_factory("alice")
    token = login("alice")
    resp = client.post("/job/delete", data={"user_id": "alice", "token": token, "job_id": "nope"})
    assert resp.status_code == 404
    assert _queue(app_module_fixture) == []
