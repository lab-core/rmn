"""Ownership scoping (IDOR) on the job-mutating routes.

Each route must reject a job that does not belong to the caller (404) and
accept the owner's own job.
"""

import io

import pytest

# (route, extra form fields) for the simple eval_jobs mutations
SIMPLE_MUTATIONS = [
    ("/jobs/update/bonus", {"bonus_enabled_map": '[["Q1", true]]'}),
    ("/jobs/update/stats", {"statistics_for_students": "false"}),
    ("/jobs/update/status", {"job_status": "ARCHIVED"}),
]

# routes with side effects; we only assert the security (foreign -> 404) here
SIDE_EFFECT_MUTATIONS = [
    ("/jobs/ignore", {}),
    ("/jobs/validate", {}),
]


def _auth(user, token, job_id, extra):
    return {"user_id": user, "token": token, "job_id": job_id, **extra}


@pytest.mark.parametrize("route,extra", SIMPLE_MUTATIONS + SIDE_EFFECT_MUTATIONS)
def test_foreign_user_cannot_mutate(client, user_factory, job_factory, login, route, extra):
    user_factory("alice")
    user_factory("bob")
    job_factory("job1", owner="alice", status="RETRY")
    bob_token = login("bob")
    resp = client.post(route, data=_auth("bob", bob_token, "job1", extra))
    assert resp.status_code == 404


@pytest.mark.parametrize("route,extra", SIMPLE_MUTATIONS)
def test_owner_can_mutate(client, user_factory, job_factory, login, route, extra):
    user_factory("alice")
    job_factory("job1", owner="alice", status="RETRY")
    token = login("alice")
    resp = client.post(route, data=_auth("alice", token, "job1", extra))
    assert resp.status_code == 200


@pytest.mark.parametrize("route,extra", SIMPLE_MUTATIONS + SIDE_EFFECT_MUTATIONS)
def test_unknown_job_returns_404_not_500(client, user_factory, login, route, extra):
    user_factory("alice")
    token = login("alice")
    resp = client.post(route, data=_auth("alice", token, "does-not-exist", extra))
    assert resp.status_code == 404


def test_foreign_user_cannot_update_csv(client, user_factory, job_factory, login):
    user_factory("alice")
    user_factory("bob")
    job_factory("job1", owner="alice")
    bob_token = login("bob")
    data = {
        "user_id": "bob",
        "token": bob_token,
        "job_id": "job1",
        "csv": (io.BytesIO(b"Matricule,Nom complet\n1,A B\n"), "notes.csv"),
    }
    resp = client.post("/jobs/update/csv", data=data, content_type="multipart/form-data")
    assert resp.status_code == 404


def test_foreign_user_cannot_add_copies(client, user_factory, job_factory, login):
    user_factory("alice")
    user_factory("bob")
    job_factory("job1", owner="alice", status="VALIDATION")
    bob_token = login("bob")
    data = {
        "user_id": "bob",
        "token": bob_token,
        "job_id": "job1",
        "file": (io.BytesIO(b"%PDF-1.4\n"), "copie.pdf"),
    }
    resp = client.post("/jobs/continue", data=data, content_type="multipart/form-data")
    assert resp.status_code == 404
