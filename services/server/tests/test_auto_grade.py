"""Serving what the grade reader found, and asking it to read.

The server starts a reading pass and hands the result to the correction
screen; the executor does the reading. What matters here is that a pass is
queued per question with the run number that lets a later upload overtake it,
and that nothing the reader produced is mistaken for a confirmed grade.
"""

import datetime
import json

from rmn_common import auto_grade
from service.documents import start_reading_grades
from rmn_common.status import Document_Status

HEADERS = {"X-Admin-Key": "test-admin-key"}
JOB = "job-reading"


def add_question(mongo, document_index, question_index=3, **extra):
    doc = {
        "job_id": JOB,
        "document_index": document_index,
        "question_index": question_index,
        "question": f"Q{question_index}",
        "basename": f"copy{document_index}",
        "filename": f"copy{document_index}_Q{question_index}",
        "status": Document_Status.TO_VALIDATE.value,
        "grade": None,
    }
    if "status" in extra and hasattr(extra["status"], "value"):
        extra["status"] = extra["status"].value
    doc.update(extra)
    mongo["job_questions"].insert_one(doc)


def make_reading_job(mongo, questions=(3,)):
    mongo["eval_jobs"].insert_one(
        {
            "job_id": JOB,
            "user_id": "alice",
            "job_status": "VALIDATION",
            # the fields POST /job serves unconditionally
            "job_name": "Examen",
            "queued_time": datetime.datetime.now(datetime.UTC),
            "students_list": [],
            "statistics_for_students": False,
            "n_max_points_per_question": [["Q3", 12]],
            "n_pages_per_question": [["Q3", 2]],
            "bonus_enabled_map": [["Q3", False]],
        }
    )
    for index, question in enumerate(questions):
        add_question(mongo, index, question_index=question)


def test_documents_serves_what_the_reader_found(
    client, app_module_fixture, login, user_factory
):
    mongo = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    token = login("alice")
    make_reading_job(mongo)
    mongo["job_questions"].update_one(
        {"job_id": JOB, "document_index": 0},
        {
            "$set": {
                "auto_grade": 9.5,
                "auto_grade_confidence": 0.97,
                "auto_grade_reason": "ok",
                "auto_grade_source": "ink",
            }
        },
    )

    resp = client.post(
        "/documents",
        data={"job_id": JOB, "questions": "true", "token": token},
    )

    assert resp.status_code == 200
    document = resp.get_json(force=True)["response"][0]
    assert document["auto_grade"] == 9.5
    assert document["auto_grade_confidence"] == 0.97
    assert document["auto_grade_source"] == "ink"
    # the reading is offered beside the grade, never as the grade
    assert document["grade"] is None
    assert document["status"] == Document_Status.TO_VALIDATE.value


def test_documents_still_serves_rows_written_before_the_feature(
    client, app_module_fixture, login, user_factory
):
    mongo = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    token = login("alice")
    make_reading_job(mongo)

    resp = client.post(
        "/documents", data={"job_id": JOB, "questions": "true", "token": token}
    )

    assert resp.status_code == 200
    assert resp.get_json(force=True)["response"][0]["auto_grade"] is None


def test_a_pass_is_queued_per_question_with_its_run(client, app_module_fixture):
    mongo = app_module_fixture.mongo["RMN"]
    redis = app_module_fixture.redis
    make_reading_job(mongo, questions=(3, 5))

    start_reading_grades(JOB, [3, 5])

    queued = [json.loads(item) for item in redis.lrange("job_queue", 0, -1)]
    assert [item["question_index"] for item in queued] == [3, 5]
    assert all(item["read_grades"] for item in queued)
    assert all(item["job_id"] == JOB for item in queued)
    # the run is what lets a later upload overtake this pass
    assert [item["run"] for item in queued] == [1, 1]
    assert auto_grade.current_run(mongo["eval_jobs"], JOB, 3) == 1


def test_a_second_upload_of_a_question_overtakes_the_first(client, app_module_fixture):
    mongo = app_module_fixture.mongo["RMN"]
    redis = app_module_fixture.redis
    make_reading_job(mongo)

    start_reading_grades(JOB, [3])
    start_reading_grades(JOB, [3])

    queued = [json.loads(item) for item in redis.lrange("job_queue", 0, -1)]
    assert [item["run"] for item in queued] == [1, 2]
    assert auto_grade.current_run(mongo["eval_jobs"], JOB, 3) == 2


def test_a_confirmed_grade_is_not_queued_for_re_reading(client, app_module_fixture):
    mongo = app_module_fixture.mongo["RMN"]
    make_reading_job(mongo)
    add_question(mongo, 1, status=Document_Status.VALIDATED, grade=8.0)

    start_reading_grades(JOB, [3])

    run = auto_grade.current_run(mongo["eval_jobs"], JOB, 3)
    pending = auto_grade.pending_documents(mongo["job_questions"], JOB, 3, run)
    assert [doc["document_index"] for doc in pending] == [0]


def test_read_grades_queues_every_question_of_the_job(
    client, app_module_fixture, login, user_factory
):
    mongo = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    token = login("alice")
    make_reading_job(mongo, questions=(3, 5))

    resp = client.post("/documents/read_grades", data={"job_id": JOB, "token": token})

    assert resp.status_code == 200
    assert resp.get_json(force=True)["questions"] == [3, 5]
    queued = [
        json.loads(i) for i in app_module_fixture.redis.lrange("job_queue", 0, -1)
    ]
    assert [item["question_index"] for item in queued] == [3, 5]


def test_read_grades_can_be_limited_to_one_question(
    client, app_module_fixture, login, user_factory
):
    mongo = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    token = login("alice")
    make_reading_job(mongo, questions=(3, 5))

    resp = client.post(
        "/documents/read_grades",
        data={"job_id": JOB, "question_index": "5", "token": token},
    )

    assert resp.get_json(force=True)["questions"] == [5]
    assert auto_grade.current_run(mongo["eval_jobs"], JOB, 3) == 0


def test_read_grades_rejects_an_unreachable_job_and_a_bad_question(
    client, app_module_fixture, login, user_factory
):
    mongo = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    token = login("alice")
    make_reading_job(mongo)

    # the share-token guard runs first and answers 401 for anything it cannot
    # resolve to a job of this user, a missing job_id included; the handler's
    # own checks are the ones it lets through
    missing = client.post("/documents/read_grades", data={"job_id": "nope", "token": token})
    bad = client.post(
        "/documents/read_grades",
        data={"job_id": JOB, "question_index": "soon", "token": token},
    )
    none = client.post("/documents/read_grades", data={"token": token})

    assert missing.status_code == 401
    assert none.status_code == 401
    assert bad.status_code == 400


def test_a_grade_in_the_csv_does_not_call_off_the_whole_reading(
    client, app_module_fixture
):
    """A grade supplied for one copy used to cancel the reading for all of them.

    start_run only queues documents that have no grade, so the two mechanisms
    already coexist: the csv wins for the copies it covers, the reader takes
    the rest.
    """
    mongo = app_module_fixture.mongo["RMN"]
    make_reading_job(mongo)
    add_question(mongo, 1)
    add_question(mongo, 2)
    # the upload carried a grade for one of the three copies
    mongo["job_questions"].update_one(
        {"job_id": JOB, "document_index": 0},
        {"$set": {"grade": 7.0, "status": Document_Status.VALIDATED.value}},
    )

    start_reading_grades(JOB, [3])

    run = auto_grade.current_run(mongo["eval_jobs"], JOB, 3)
    queued = auto_grade.pending_documents(mongo["job_questions"], JOB, 3, run)
    assert [d["document_index"] for d in queued] == [1, 2]


def test_progress_counts_a_copy_the_teacher_graded_as_done_not_as_owing(
    client, app_module_fixture, login, user_factory
):
    """ "Q1 : lues 16/15" -- the count the teacher was shown made no sense.

    A copy graded by hand is never read, so it sat outside the states the
    progress was derived from while still counting towards the total. It is
    the teacher's, not the reader's: it is reported separately and the two
    halves add up to the whole question again.
    """
    mongo = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    token = login("alice")
    make_reading_job(mongo)
    add_question(mongo, 1, auto_grade_status=auto_grade.DONE, auto_grade_run=1)
    # read, and then graded by hand before the teacher reached the screen
    add_question(
        mongo,
        2,
        auto_grade_status=auto_grade.DONE,
        auto_grade_run=1,
        grade=7.0,
        status=Document_Status.VALIDATED,
    )
    add_question(mongo, 3, auto_grade_status=auto_grade.PENDING, auto_grade_run=1)
    mongo["job_questions"].update_one(
        {"job_id": JOB, "document_index": 0},
        {"$set": {"auto_grade_status": auto_grade.RUNNING, "auto_grade_run": 1}},
    )

    resp = client.post("/jobs/info", data={"job_id": JOB, "token": token})

    progress = resp.get_json(force=True)["response"]["auto_grade_progress"]["3"]
    assert progress == {
        "pending": 1,
        "running": 1,
        "done": 1,
        "graded": 1,
        "total": 4,
    }
    # what the screen adds up: nothing is counted twice and nothing is missing
    assert (
        progress["pending"]
        + progress["running"]
        + progress["done"]
        + progress["graded"]
        == progress["total"]
    )


def test_progress_says_nothing_about_a_question_no_reading_has_touched(
    client, app_module_fixture, login, user_factory
):
    mongo = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    token = login("alice")
    make_reading_job(mongo, questions=(3, 5))
    mongo["job_questions"].update_one(
        {"job_id": JOB, "question_index": 3},
        {"$set": {"auto_grade_status": auto_grade.DONE, "auto_grade_run": 1}},
    )

    resp = client.post("/jobs/info", data={"job_id": JOB, "token": token})

    progress = resp.get_json(force=True)["response"]["auto_grade_progress"]
    assert list(progress) == ["3"]
