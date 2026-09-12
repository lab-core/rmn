"""The executor's MongoDB wrapper, against mongomock."""

import datetime as dt

from process_copy.database import Database
from rmn_common.status import Document_Status, Job_Status


def test_insert_question_derives_the_index_from_the_key(mongo_db):
    db = Database()
    db.insert_question("job", 0, "documents/job/Q3/a_Q3.pdf", Document_Status.TO_VALIDATE, "a_Q3", "Q3", "a")
    db.insert_question(
        "job", 1, "documents/job/Q1/a_Q1.pdf", Document_Status.VALIDATED, "a_Q1", "Q1", "a",
        question_index=7, grade=2.5,
    )

    q3, q1 = mongo_db["job_questions"].find({"job_id": "job"}).sort("document_index")
    assert (q3["question_index"], q3["grade"], q3["status"]) == (3, None, "TO VALIDATE")
    assert (q1["question_index"], q1["grade"], q1["status"]) == (7, 2.5, "VALIDATED")
    assert q3["basename"] == "a" and q3["filename"] == "a_Q3"


def test_documents_round_trip(mongo_db):
    db = Database()
    db.insert_document("job", 0, [None, None], "cover_pages/job/a_cover.pdf",
                       Document_Status.NOT_READY, 1234567, 0, "a")

    doc = db.get_document("job", 0)
    assert doc["matricule"] == "1234567"  # stored as text
    assert doc["status"] == "NOT_READY"

    assert db.update_document("job", 0, [5, 3], Document_Status.HIGH_ACCURACY, "2345678", 1.5, "A") is True
    doc = db.get_document("job", 0)
    assert doc["grades"] == [5, 3]
    assert doc["group"] == "A"
    assert doc["status"] == "HIGH ACCURACY"
    assert doc["execution_time"] == 1.5

    # None leaves grades and group untouched
    assert db.update_document("job", 0, None, Document_Status.VALIDATED, "2345678", 2, None) is True
    doc = db.get_document("job", 0)
    assert doc["grades"] == [5, 3] and doc["group"] == "A" and doc["status"] == "VALIDATED"

    assert db.update_document("job", 9, [1], Document_Status.VALIDATED, "x", 0, None) is False
    assert db.update_document_grades("job", 0, [1, 1]) is True
    assert db.get_document("job", 0)["grades"] == [1, 1]
    assert db.update_document_grades("job", 9, [1, 1]) is False


def test_job_max_questions_and_run_status(mongo_db):
    mongo_db["eval_jobs"].insert_one({"job_id": "job", "job_status": "QUEUED"})
    db = Database()

    assert db.get_job_max_questions("job") is None
    db.set_job_max_questions("job", 4)
    assert db.get_job_max_questions("job") == 4
    assert isinstance(mongo_db["eval_jobs"].find_one({"job_id": "job"})["alive_time"], dt.datetime)
    assert db.get_job_max_questions("nope") is None

    job = db.update_job_status_to_run("job", ["1234567"], groups=["A"])
    assert job["job_status"] == Job_Status.RUN.value
    assert job["students_list"] == ["1234567"]
    assert job["groups"] == ["A"]

    job = db.update_job_status_to_run("job", [])
    assert job["groups"] == ["A"]  # not reset when omitted


def test_templates_info(mongo_db):
    mongo_db["template"].insert_many(
        [
            {"template_id": "front", "grade_box": [0.1, 0.9, 0.6, 0.9], "matricule_box": [0.05, 0.85, 0.15, 0.35]},
            {"template_id": "regular", "matricule_box": [0.55, 0.95, 0.05, 0.13]},
        ]
    )
    db = Database()
    assert db.get_templates_info("front", "regular") == (
        [0.1, 0.9, 0.6, 0.9],
        [0.05, 0.85, 0.15, 0.35],
        [0.55, 0.95, 0.05, 0.13],
    )
    assert db.get_templates_info("front") == ([0.1, 0.9, 0.6, 0.9], [0.05, 0.85, 0.15, 0.35], None)


def test_collections_are_named_as_the_server_expects(mongo_db):
    db = Database()
    assert db.documents_collection().name == "job_documents"
    assert db.questions_collection().name == "job_questions"
    assert db.eval_jobs_collection().name == "eval_jobs"
    assert db.jobs_output_collection().name == "jobs_output"
    assert db.users_collection().name == "users"
