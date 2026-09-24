"""A single-question share link can only touch its own question.

The scope check used to run after the write (``/documents/replace``) or only
on the grades branch (``/document/update``), so a Q1 link could overwrite the
Q7 files of the whole cohort.
"""

import io
import json
import os
import zipfile

import pytest
from routes import documents as documents_routes


def _questions(mongo, job_id):
    mongo["RMN"]["job_questions"].insert_many(
        [
            {
                "job_id": job_id,
                "document_index": 0,
                "question_index": 1,
                "question": "Q1",
                "basename": "copy1",
                "filename": "copy1_Q1",
                "status": "TO VALIDATE",
                "grade": None,
            },
            {
                "job_id": job_id,
                "document_index": 1,
                "question_index": 7,
                "question": "Q7",
                "basename": "copy1",
                "filename": "copy1_Q7",
                "status": "TO VALIDATE",
                "grade": None,
            },
        ]
    )
    mongo["RMN"]["job_documents"].insert_one(
        {
            "job_id": job_id,
            "document_index": 0,
            "filename": "copy1",
            "status": "TO VALIDATE",
            "grades": [None] * 7,
        }
    )


@pytest.fixture
def shared_job(job_factory, app_module_fixture):
    # the share key is the question_index the client sends back with the token
    job_factory("j1", "alice", share_token={"1": "tok-q1", "questions": "tok-all"})
    _questions(app_module_fixture.mongo, "j1")
    return app_module_fixture


def _q1(**extra):
    return {"job_id": "j1", "share_token": "tok-q1", "question_index": "1", **extra}


def _pdf(name):
    return (io.BytesIO(b"%PDF-1.4 test"), name)


def _touch(storage, rel):
    path = storage.abs_path(rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    return path


def test_q1_link_cannot_upload_a_file_for_another_question(client, shared_job):
    storage = shared_job.storage
    resp = client.post(
        "/document/update",
        data=_q1(document_index="1", status="VALIDATED", file=_pdf("copy1_Q7.pdf")),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 401
    assert not os.path.exists(storage.abs_path("documents/j1/Q7"))
    assert shared_job.mongo["RMN"]["versions"].count_documents({}) == 0


def test_q1_link_can_upload_its_own_question(client, shared_job):
    storage = shared_job.storage
    _touch(storage, "documents/j1/Q1/copy1_Q1.pdf")
    os.makedirs(storage.abs_path("documents/j1/Q1/versions"), exist_ok=True)

    resp = client.post(
        "/document/update",
        data=_q1(document_index="0", status="VALIDATED", file=_pdf("copy1_Q1.pdf")),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200, resp.data
    assert shared_job.mongo["RMN"]["versions"].count_documents({"job_id": "j1"}) == 1
    assert (
        open(storage.abs_path("documents/j1/Q1/copy1_Q1.pdf"), "rb")
        .read()
        .startswith(b"%PDF")
    )


def test_q1_link_cannot_grade_another_question(client, shared_job):
    resp = client.post(
        "/document/update", data=_q1(document_index="1", status="VALIDATED", grades="3")
    )
    assert resp.status_code == 401
    q7 = shared_job.mongo["RMN"]["job_questions"].find_one(
        {"job_id": "j1", "document_index": 1}
    )
    assert q7["status"] == "TO VALIDATE" and q7["grade"] is None


def test_owner_cannot_escape_the_question_folder_through_the_filename(
    client, shared_job, user_factory, login
):
    user_factory("alice")
    token = login("alice")
    resp = client.post(
        "/document/update",
        data={
            "user_id": "alice",
            "token": token,
            "job_id": "j1",
            "document_index": "0",
            "status": "VALIDATED",
            "file": _pdf("x_...pdf"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert not os.path.exists(shared_job.storage.abs_path("documents/x_...pdf"))


class _SyncThread:
    """Run the background work inline so the test can observe it."""

    def __init__(self, target, args):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


def test_replace_checks_the_scope_before_writing_the_grade(
    client, shared_job, monkeypatch
):
    monkeypatch.setattr(documents_routes, "Thread", _SyncThread)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w"):
        pass
    buf.seek(0)

    resp = client.post(
        "/documents/replace",
        data=_q1(grades=json.dumps({"0": 5, "1": 100}), file=(buf, "copies.zip")),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200

    questions = shared_job.mongo["RMN"]["job_questions"]
    q1 = questions.find_one({"job_id": "j1", "document_index": 0})
    q7 = questions.find_one({"job_id": "j1", "document_index": 1})
    assert (q1["status"], q1["grade"]) == ("VALIDATED", 5)
    assert (q7["status"], q7["grade"]) == ("TO VALIDATE", None)
    assert (
        shared_job.mongo["RMN"]["job_documents"].find_one({"job_id": "j1"})["grades"][0]
        == 5
    )
    # and the answer says so: the drop used to happen in silence, inside a
    # thread whose 200 had already been sent
    assert resp.get_json(force=True)["skipped_questions"] == ["Q7"]


def test_q1_link_cannot_tag_another_question(client, shared_job):
    # /document/tag ignored the share-token scope
    questions = shared_job.mongo["RMN"]["job_questions"]
    assert client.post("/document/tag", data=_q1(document_index="1", tag="doubt")).status_code == 401
    assert questions.find_one({"job_id": "j1", "document_index": 1}).get("tag") is None
    assert client.post("/document/tag", data=_q1(document_index="0", tag="doubt")).status_code == 200
    assert questions.find_one({"job_id": "j1", "document_index": 0})["tag"] == "doubt"
    assert client.post("/document/tag", data=_q1(document_index="9", tag="doubt")).status_code == 404


def test_owner_can_save_the_grades_of_a_whole_copy(client, shared_job, user_factory, login):
    # the branch without question_index iterated the JSON text character by
    # character and then returned 404 whatever happened
    user_factory("alice")
    token = login("alice")
    base = {"job_id": "j1", "user_id": "alice", "token": token, "document_index": "0", "status": "VALIDATED"}
    resp = client.post("/document/update", data={**base, "grades": json.dumps([1, 2.5, 0, 0, 0, 0, 3])})
    assert resp.status_code == 200, resp.data
    doc = shared_job.mongo["RMN"]["job_documents"].find_one({"job_id": "j1", "document_index": 0})
    assert doc["grades"] == [1.0, 2.5, 0.0, 0.0, 0.0, 0.0, 3.0]
    assert doc["status"] == "VALIDATED"

    assert client.post("/document/update", data={**base, "grades": "not json"}).status_code == 400
    assert client.post("/document/update", data={**base, "document_index": "9", "grades": "[1]"}).status_code == 404


def test_replace_names_the_questions_of_the_zip_it_refuses(
    client, shared_job, monkeypatch
):
    """The export puts the whole task in one zip, so a Q1 link sends Q7 too."""
    monkeypatch.setattr(documents_routes, "Thread", _SyncThread)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("copy1_Q1.pdf", b"%PDF-1.4 one")
        archive.writestr("copy1_Q7.pdf", b"%PDF-1.4 seven")
    buf.seek(0)

    resp = client.post(
        "/documents/replace",
        data=_q1(grades=json.dumps({}), file=(buf, "copies.zip")),
        content_type="multipart/form-data",
    )

    assert resp.get_json(force=True)["skipped_questions"] == ["Q7"]
    storage = shared_job.storage
    assert os.path.exists(storage.abs_path("documents/j1/Q1/copy1_Q1.pdf"))
    assert not os.path.exists(storage.abs_path("documents/j1/Q7"))


def test_replace_reports_nothing_when_the_whole_upload_is_written(
    client, app_module_fixture, monkeypatch, login, user_factory, job_factory
):
    """The owner may touch every question, so there is nothing to warn about."""
    monkeypatch.setattr(documents_routes, "Thread", _SyncThread)
    user_factory("alice")
    token = login("alice")
    job_factory("j2", "alice")
    _questions(app_module_fixture.mongo, "j2")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("copy1_Q1.pdf", b"%PDF-1.4 one")
        archive.writestr("copy1_Q7.pdf", b"%PDF-1.4 seven")
    buf.seek(0)

    resp = client.post(
        "/documents/replace",
        data={
            "job_id": "j2",
            "token": token,
            "grades": json.dumps({"0": 5, "1": 6}),
            "read_grades": "false",
            "file": (buf, "copies.zip"),
        },
        content_type="multipart/form-data",
    )

    assert resp.get_json(force=True)["skipped_questions"] == []
    storage = app_module_fixture.storage
    assert os.path.exists(storage.abs_path("documents/j2/Q7/copy1_Q7.pdf"))
