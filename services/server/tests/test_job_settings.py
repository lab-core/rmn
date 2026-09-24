"""Editing a task after creation: name, points and pages per question."""

import json
import os
from zipfile import ZipFile

import pytest

QUESTIONS = {
    "n_pages_per_question": [["Q1", 1], ["Q2", 2], ["Q3", 0]],
    "n_max_points_per_question": [["Q1", 10], ["Q2", 5], ["Q3", 0]],
    "bonus_enabled_map": [["Q1", False], ["Q2", True], ["Q3", False]],
}


def _queue(app_module):
    return [json.loads(p) for p in app_module.redis.lrange("job_queue", 0, -1)]


@pytest.fixture
def alice(client, user_factory, login):
    user_factory("alice")
    token = login("alice")

    def post(**form):
        return client.post("/jobs/update/settings", data={"user_id": "alice", "token": token, **form})

    return post


def _job(app_module):
    return app_module.mongo["RMN"]["eval_jobs"].find_one({"job_id": "j1"})


def test_the_name_can_change_at_any_stage(alice, job_factory, app_module_fixture):
    job_factory("j1", "alice", status="ARCHIVED", **QUESTIONS)

    assert alice(job_id="j1", job_name="  Intra A26  ").status_code == 200
    assert _job(app_module_fixture)["job_name"] == "Intra A26"

    assert alice(job_id="j1", job_name="   ").status_code == 400
    assert alice(job_id="j1", job_name="x" * 201).status_code == 400
    assert _job(app_module_fixture)["job_name"] == "Intra A26"


def test_the_points_change_until_the_task_is_validated(alice, job_factory, app_module_fixture):
    job_factory("j1", "alice", status="VALIDATION", **QUESTIONS)
    points = [["Q1", 12], ["Q2", 5], ["Q3", 0]]

    assert alice(job_id="j1", n_max_points_per_question=json.dumps(points)).status_code == 200
    assert _job(app_module_fixture)["n_max_points_per_question"] == points

    for status in ("VALIDATED", "FINALIZING", "ARCHIVED"):
        app_module_fixture.mongo["RMN"]["eval_jobs"].update_one({"job_id": "j1"}, {"$set": {"job_status": status}})
        resp = alice(job_id="j1", n_max_points_per_question=json.dumps([["Q1", 20], ["Q2", 5], ["Q3", 0]]))
        assert resp.status_code == 409, status
    assert _job(app_module_fixture)["n_max_points_per_question"] == points


def test_points_that_do_not_fit_the_task_are_refused(alice, job_factory, app_module_fixture):
    job_factory("j1", "alice", status="VALIDATION", **QUESTIONS)
    refused = [
        [["Q1", 10], ["Q2", 5]],  # a question missing
        [["Q1", 10], ["Q2", 5], ["Q4", 0]],  # another task's questions
        [["Q1", 0], ["Q2", 5], ["Q3", 0]],  # a corrected question worth nothing
        [["Q1", 10], ["Q2", 5], ["Q3", 2]],  # an ignored question worth points
        [["Q1", -1], ["Q2", 5], ["Q3", 0]],
    ]
    for points in refused:
        assert alice(job_id="j1", n_max_points_per_question=json.dumps(points)).status_code == 400, points
    assert alice(job_id="j1", n_max_points_per_question="not json").status_code == 400
    assert _job(app_module_fixture)["n_max_points_per_question"] == QUESTIONS["n_max_points_per_question"]


def test_a_grade_above_a_lowered_maximum_goes_back_to_validation(alice, job_factory, app_module_fixture):
    job_factory("j1", "alice", status="VALIDATION", **QUESTIONS)
    questions = app_module_fixture.mongo["RMN"]["job_questions"]
    rows = [
        (0, 1, 9, "VALIDATED"),  # above the new max of Q1: flagged
        (1, 1, 6, "VALIDATED"),  # still within it
        (2, 1, 8, "HIGH ACCURACY"),  # flagged too
        (3, 2, 7, "VALIDATED"),  # Q2 is a bonus question: may go above
        (4, 1, None, "TO VALIDATE"),
    ]
    questions.insert_many([
        {"job_id": "j1", "document_index": i, "question_index": q, "question": f"Q{q}", "grade": g, "status": st}
        for i, q, g, st in rows
    ])

    resp = alice(job_id="j1", n_max_points_per_question=json.dumps([["Q1", 7], ["Q2", 3], ["Q3", 0]]))

    assert resp.status_code == 200
    assert resp.get_json(force=True)["flagged"] == 2
    status = {d["document_index"]: d["status"] for d in questions.find({"job_id": "j1"})}
    assert status == {0: "TO VALIDATE", 1: "VALIDATED", 2: "TO VALIDATE", 3: "VALIDATED", 4: "TO VALIDATE"}


def test_new_pages_split_the_rejected_copies_again(alice, job_factory, app_module_fixture):
    job_factory("j1", "alice", status="RETRY", copies_errors=["a.pdf a 1 page de trop."],
                job_infos="1 copie invalide", **QUESTIONS)
    storage = app_module_fixture.storage
    rejected = storage.abs_path(os.path.join("incorrect_files", "j1"))
    os.makedirs(rejected, exist_ok=True)
    for name in ("a.pdf", "b.pdf"):
        with open(os.path.join(rejected, name), "wb") as f:
            f.write(b"%PDF " + name.encode())
    pages = [["Q1", 2], ["Q2", 2], ["Q3", 0]]
    zip_dir = storage.abs_path(os.path.join("zips", "j1"))
    before = set(os.listdir(zip_dir)) if os.path.isdir(zip_dir) else set()  # the storage outlives a test

    resp = alice(job_id="j1", n_pages_per_question=json.dumps(pages))

    assert resp.status_code == 200
    assert resp.get_json(force=True)["resplit"] == 2
    job = _job(app_module_fixture)
    assert job["n_pages_per_question"] == pages
    # like copies added from the retry dialog: the executor splits the zip
    assert job["job_status"] == "CORRECTED"
    assert "copies_errors" not in job and "job_infos" not in job
    assert _queue(app_module_fixture) == [{"job_id": "j1", "add_copies": True}]
    assert not os.path.exists(rejected)
    zips = sorted(set(os.listdir(zip_dir)) - before)
    assert len(zips) == 1
    with ZipFile(os.path.join(zip_dir, zips[0])) as z:
        assert sorted(z.namelist()) == ["a.pdf", "b.pdf"]
        assert z.read("a.pdf") == b"%PDF a.pdf"


def test_pages_cannot_change_once_copies_are_split(alice, job_factory, app_module_fixture):
    pages = json.dumps([["Q1", 2], ["Q2", 2], ["Q3", 0]])

    # the copies were accepted: the task is being corrected
    job_factory("j1", "alice", status="VALIDATION", **QUESTIONS)
    assert alice(job_id="j1", n_pages_per_question=pages).status_code == 409

    # some copies were split, the others rejected: both would be cut differently
    app_module_fixture.mongo["RMN"]["eval_jobs"].update_one({"job_id": "j1"}, {"$set": {"job_status": "RETRY"}})
    app_module_fixture.mongo["RMN"]["job_questions"].insert_one({"job_id": "j1", "document_index": 0})
    assert alice(job_id="j1", n_pages_per_question=pages).status_code == 409

    assert _job(app_module_fixture)["n_pages_per_question"] == QUESTIONS["n_pages_per_question"]
    assert _queue(app_module_fixture) == []


def test_pages_must_keep_the_ignored_questions_ignored(alice, job_factory, app_module_fixture):
    job_factory("j1", "alice", status="RETRY", **QUESTIONS)
    # Q3 is worth 0 point: it cannot get pages without points
    assert alice(job_id="j1", n_pages_per_question=json.dumps([["Q1", 1], ["Q2", 2], ["Q3", 1]])).status_code == 400
    # but both can change together
    resp = alice(job_id="j1", n_pages_per_question=json.dumps([["Q1", 1], ["Q2", 2], ["Q3", 1]]),
                 n_max_points_per_question=json.dumps([["Q1", 10], ["Q2", 5], ["Q3", 4]]))
    assert resp.status_code == 200
    assert _job(app_module_fixture)["n_max_points_per_question"][2] == ["Q3", 4]


def test_only_the_owner_can_edit_and_something_must_change(client, alice, user_factory, login, job_factory,
                                                           app_module_fixture):
    job_factory("j1", "alice", status="VALIDATION", **QUESTIONS)
    user_factory("bob")
    bob = login("bob")

    resp = client.post("/jobs/update/settings", data={"user_id": "bob", "token": bob, "job_id": "j1",
                                                    "job_name": "mine"})
    assert resp.status_code == 404
    assert _job(app_module_fixture)["job_name"] == "test job"
    assert alice(job_id="j1").status_code == 400
    assert alice(job_name="x").status_code == 400
