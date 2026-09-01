"""Integration tests for POST /job/delete.

The endpoint removes the job record synchronously and runs the storage +
ancillary cleanup on a background thread. The ``sync_threads`` fixture makes
that thread run inline so the cleanup assertions are deterministic.
"""

import os

import pytest


class _SyncThread:
    """Drop-in for threading.Thread that runs the target synchronously."""

    started = []

    def __init__(self, target=None, args=(), kwargs=None, **_):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        _SyncThread.started.append((self._target, self._args))
        if self._target:
            self._target(*self._args, **self._kwargs)


@pytest.fixture
def sync_threads(monkeypatch, app_module_fixture):
    _SyncThread.started = []
    monkeypatch.setattr(app_module_fixture, "Thread", _SyncThread)
    return _SyncThread


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


def test_delete_removes_job_everywhere(sync_threads, client, user_factory, job_factory, login, app_module_fixture):
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


def test_delete_backgrounds_the_cleanup(sync_threads, client, user_factory, job_factory, login, app_module_fixture):
    user_factory("alice")
    job_factory("job1", owner="alice")
    token = login("alice")

    resp = client.post("/job/delete", data={"user_id": "alice", "token": token, "job_id": "job1"})
    assert resp.status_code == 200
    # cleanup was handed to a background thread running delete_job, not inline
    assert sync_threads.started
    target, args = sync_threads.started[0]
    assert target is app_module_fixture.delete_job
    assert args == ["job1"]


def test_delete_removes_record_synchronously(monkeypatch, client, user_factory, job_factory, login, app_module_fixture):
    # a Thread whose target never runs proves the eval_jobs record is deleted
    # inline (not by the background cleanup)
    class _DeadThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    monkeypatch.setattr(app_module_fixture, "Thread", _DeadThread)
    user_factory("alice")
    job_factory("job1", owner="alice")
    token = login("alice")
    resp = client.post("/job/delete", data={"user_id": "alice", "token": token, "job_id": "job1"})
    assert resp.status_code == 200
    assert app_module_fixture.mongo["RMN"]["eval_jobs"].count_documents({"job_id": "job1"}) == 0


def test_delete_foreign_job_is_rejected(sync_threads, client, user_factory, job_factory, login, app_module_fixture):
    user_factory("alice")
    user_factory("bob")
    job_factory("job1", owner="alice")
    _seed_storage(app_module_fixture, "job1")
    bob_token = login("bob")

    resp = client.post("/job/delete", data={"user_id": "bob", "token": bob_token, "job_id": "job1"})
    assert resp.status_code == 404
    # no background cleanup was triggered, and alice's job/storage is intact
    assert not sync_threads.started
    db = app_module_fixture.mongo["RMN"]
    assert db["eval_jobs"].count_documents({"job_id": "job1"}) == 1
    assert os.path.exists(app_module_fixture.storage.abs_path(os.path.join("documents", "job1")))


def test_delete_unknown_job_returns_404(sync_threads, client, user_factory, login):
    user_factory("alice")
    token = login("alice")
    resp = client.post("/job/delete", data={"user_id": "alice", "token": token, "job_id": "nope"})
    assert resp.status_code == 404
    assert not sync_threads.started
