"""Reading the matricules or the grades of a job again, from its page."""

import json

import pytest

from rmn_common.status import Document_Status, Job_Status

JOB = "job-read-again"


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def db(app_module_fixture):
    return app_module_fixture.mongo["RMN"]


@pytest.fixture
def queue(app_module_fixture):
    app_module_fixture.redis.delete("job_queue")
    return lambda: [
        json.loads(i) for i in app_module_fixture.redis.lrange("job_queue", 0, -1)
    ]


def _documents(db, *statuses):
    for index, status in enumerate(statuses):
        db["job_documents"].insert_one(
            {
                "job_id": JOB,
                "document_index": index,
                "status": status.value,
                "matricule": f"20{index:05d}",
                "matricule_confidence": 0.5,
                "filename": f"copy{index}.pdf",
            }
        )


def _read_matricules(client, token, user="alice", job_id=JOB):
    return client.post(
        "/jobs/read_matricules",
        data={"user_id": user, "job_id": job_id},
        headers=_auth(token),
    )


def test_only_the_copies_nobody_validated_are_read_again(
    client, user_factory, job_factory, login, db, queue
):
    user_factory("alice")
    job_factory(JOB, "alice", status=Job_Status.VALIDATION.value, job_infos="old")
    _documents(
        db,
        Document_Status.VALIDATED,
        Document_Status.TO_VALIDATE,
        Document_Status.HIGH_ACCURACY,
        Document_Status.DELETED,
    )

    resp = _read_matricules(client, login("alice"))
    assert resp.status_code == 200
    assert resp.get_json(force=True)["documents"] == 2

    statuses = [
        d["status"]
        for d in db["job_documents"].find({"job_id": JOB}).sort("document_index")
    ]
    assert statuses == [
        Document_Status.VALIDATED.value,
        Document_Status.NOT_READY.value,
        Document_Status.NOT_READY.value,
        Document_Status.DELETED.value,
    ]
    # the confidence of an earlier reading must not colour the copy meanwhile
    assert "matricule_confidence" not in db["job_documents"].find_one(
        {"job_id": JOB, "document_index": 1}
    )
    job = db["eval_jobs"].find_one({"job_id": JOB})
    assert job["job_status"] == Job_Status.QUEUED.value and "job_infos" not in job
    assert queue() == [{"job_id": JOB}]


def test_nothing_to_read_when_everything_is_validated(
    client, user_factory, job_factory, login, db, queue
):
    user_factory("alice")
    job_factory(JOB, "alice", status=Job_Status.VALIDATION.value)
    _documents(db, Document_Status.VALIDATED)
    assert _read_matricules(client, login("alice")).status_code == 400
    assert (
        db["eval_jobs"].find_one({"job_id": JOB})["job_status"]
        == Job_Status.VALIDATION.value
    )
    assert queue() == []


@pytest.mark.parametrize(
    "status",
    [Job_Status.RUN, Job_Status.QUEUED, Job_Status.VALIDATED, Job_Status.ARCHIVED],
)
def test_only_a_job_in_validation_is_read_again(
    client, user_factory, job_factory, login, db, queue, status
):
    user_factory("alice")
    job_factory(JOB, "alice", status=status.value)
    _documents(db, Document_Status.TO_VALIDATE)
    assert _read_matricules(client, login("alice")).status_code == 400
    assert queue() == []


def test_only_the_owner_reads_the_matricules_again(
    client, user_factory, job_factory, login, db, queue
):
    user_factory("alice")
    user_factory("bob")
    job_factory(JOB, "alice", status=Job_Status.VALIDATION.value)
    _documents(db, Document_Status.TO_VALIDATE)
    assert _read_matricules(client, login("bob"), user="bob").status_code == 404
    assert _read_matricules(client, login("alice"), job_id="").status_code == 404
    assert queue() == []


@pytest.mark.parametrize(
    "status", [Job_Status.VALIDATED, Job_Status.ARCHIVED, Job_Status.ERROR]
)
def test_the_grades_are_read_only_while_the_job_is_corrected(
    client, user_factory, job_factory, login, db, queue, status
):
    user_factory("alice")
    job_factory(JOB, "alice", status=status.value)
    db["job_questions"].insert_one(
        {"job_id": JOB, "question_index": 1, "document_index": 0}
    )
    resp = client.post(
        "/documents/read_grades",
        data={"user_id": "alice", "job_id": JOB},
        headers=_auth(login("alice")),
    )
    assert resp.status_code == 400
    assert queue() == []
