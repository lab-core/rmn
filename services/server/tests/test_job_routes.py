"""Validating a task, adding copies to it, replacing its roster, its archive info.

Each route is scoped to the owner (another user's job is a 404) and hands the
work to the executor through the Redis queue.
"""

import io
import json
import os
import uuid
import zipfile

import pytest
from routes import jobs as jobs_routes


@pytest.fixture
def alice(user_factory, login):
    user_factory("alice")
    return login("alice")


@pytest.fixture
def job_id():
    # a fresh id per test: the storage root outlives a test
    return f"jobs-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def db(app_module_fixture):
    return app_module_fixture.mongo["RMN"]


def _queue(app_module):
    return [json.loads(p) for p in app_module.redis.lrange("job_queue", 0, -1)]


# ------------------------------------------------------------ /job/validate ---
def test_validate_marks_the_job_and_queues_the_finalization(
    client, alice, job_factory, job_id, db, app_module_fixture
):
    job_factory(job_id, "alice")
    db["job_documents"].insert_one({"job_id": job_id, "execution_time": 12})

    resp = client.post("/jobs/validate", data={"job_id": job_id, "token": alice})

    assert resp.status_code == 200
    assert db["eval_jobs"].find_one({"job_id": job_id})["job_status"] == "VALIDATED"
    assert db["job_documents"].find_one({"job_id": job_id})["execution_time"] == 0
    assert _queue(app_module_fixture) == [{"job_id": job_id}]


def test_validate_reports_an_unreachable_queue(
    client, alice, job_factory, job_id, monkeypatch
):
    job_factory(job_id, "alice")

    class DownRedis:
        def rpush(self, *_):
            raise ConnectionError("redis is down")

    monkeypatch.setattr(jobs_routes, "redis", DownRedis())
    resp = client.post("/jobs/validate", data={"job_id": job_id, "token": alice})
    assert resp.status_code == 500


def test_validate_requires_a_job_id(client, alice):
    assert client.post("/jobs/validate", data={"token": alice}).status_code == 400


# ------------------------------------------------------------ /job/continue ---
def _add_copies(client, token, job_id, files):
    data = {"job_id": job_id, "token": token}
    for i, (content, name) in enumerate(files):
        data[f"file{i}"] = (io.BytesIO(content), name)
    return client.post("/jobs/continue", data=data, content_type="multipart/form-data")


def test_copies_added_to_a_retrying_job_are_zipped_and_queued(
    client, alice, job_factory, job_id, db, app_module_fixture
):
    storage = app_module_fixture.storage
    job_factory(job_id, "alice", status="RETRY", job_infos="2 copies rejected")
    incorrect = storage.abs_path(f"incorrect_files/{job_id}/copy.pdf")
    os.makedirs(os.path.dirname(incorrect), exist_ok=True)
    open(incorrect, "wb").close()

    resp = _add_copies(client, alice, job_id, [(b"%PDF a", "a.pdf"), (b"%PDF b", "")])

    assert resp.status_code == 200, resp.data
    job = db["eval_jobs"].find_one({"job_id": job_id})
    assert job["job_status"] == "CORRECTED" and "job_infos" not in job
    # the rejected copies are replaced by the new upload
    assert not os.path.exists(os.path.dirname(incorrect))
    [archive] = os.listdir(storage.abs_path(f"zips/{job_id}"))

    with zipfile.ZipFile(storage.abs_path(f"zips/{job_id}/{archive}")) as zf:
        names = zf.namelist()
        assert "a.pdf" in names and len(names) == 2
        # a file without a name still gets one
        assert all(n.endswith(".pdf") for n in names)
    assert _queue(app_module_fixture) == [{"job_id": job_id, "add_copies": True}]


def test_copies_added_during_validation_keep_the_status(
    client, alice, job_factory, job_id, db
):
    job_factory(job_id, "alice", status="VALIDATION")
    resp = _add_copies(client, alice, job_id, [(b"%PDF a", "a.pdf")])
    assert resp.status_code == 200
    assert db["eval_jobs"].find_one({"job_id": job_id})["job_status"] == "VALIDATION"


def test_copies_cannot_be_added_to_a_finished_job(
    client, alice, job_factory, job_id, app_module_fixture
):
    job_factory(job_id, "alice", status="ARCHIVED")
    resp = _add_copies(client, alice, job_id, [(b"%PDF a", "a.pdf")])
    assert resp.status_code == 404
    assert not os.path.exists(app_module_fixture.storage.abs_path(f"zips/{job_id}"))
    assert _queue(app_module_fixture) == []


def test_adding_copies_needs_a_file(client, alice, job_factory, job_id):
    job_factory(job_id, "alice", status="RETRY")
    resp = client.post("/jobs/continue", data={"job_id": job_id, "token": alice})
    assert resp.status_code == 400


# ---------------------------------------------------------- /job/update/csv ---
def test_a_new_roster_replaces_the_csv_and_the_students_list(
    client, alice, job_factory, job_id, db, app_module_fixture
):
    job_factory(job_id, "alice")
    # a French Moodle export is separated by semicolons
    roster = "Matricule;Nom complet;Note\n111;Ada Lovelace;\n222;Alan Turing;\n"

    resp = client.post(
        "/jobs/update/csv",
        data={
            "job_id": job_id,
            "token": alice,
            "csv": (io.BytesIO(roster.encode()), "notes.csv"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 200, resp.data
    students = db["eval_jobs"].find_one({"job_id": job_id})["students_list"]
    assert students == [
        {"matricule": 111, "Nom complet": "Ada Lovelace"},
        {"matricule": 222, "Nom complet": "Alan Turing"},
    ]
    stored = app_module_fixture.storage.abs_path(f"output_csv/{job_id}.csv")
    with open(stored) as f:
        assert "Alan Turing" in f.read()
    os.remove(stored)


def test_a_roster_update_needs_the_csv(client, alice, job_factory, job_id):
    job_factory(job_id, "alice")
    resp = client.post("/jobs/update/csv", data={"job_id": job_id, "token": alice})
    assert resp.status_code == 400
    assert client.post("/jobs/update/csv", data={"token": alice}).status_code == 400


# ----------------------------------------------------------- /job/batch/info ---
def test_batch_info_counts_the_zips(client, alice, job_factory, job_id, db):
    job_factory(
        job_id, "alice", statistics_for_students=True, share_token={"all": "tok-all"}
    )
    db["jobs_output"].insert_one({"job_id": job_id, "zip_id_list": ["a.zip", "b.zip"]})

    for auth in ({"token": alice}, {"share_token": "tok-all"}):
        resp = client.post("/jobs/batch/info", data={"job_id": job_id, **auth})
        assert resp.status_code == 200
        assert resp.get_json(force=True) == {"nZips": 2, "stats": True}


def test_batch_info_is_refused_to_a_question_link(client, job_factory, job_id, db):
    job_factory(
        job_id,
        "alice",
        statistics_for_students=True,
        share_token={"questions": "tok-q", "mat": "tok-mat"},
    )
    db["jobs_output"].insert_one({"job_id": job_id, "zip_id_list": []})
    for token in ("tok-q", "tok-mat"):
        resp = client.post(
            "/jobs/batch/info", data={"job_id": job_id, "share_token": token}
        )
        assert resp.status_code == 401


def test_batch_info_of_a_job_without_output_is_404(client, alice, job_factory, job_id):
    job_factory(job_id, "alice", statistics_for_students=False)
    resp = client.post("/jobs/batch/info", data={"job_id": job_id, "token": alice})
    assert resp.status_code == 404
