"""The whole path a teacher takes: send graded copies back, see the grades.

Every bug this feature has shipped slipped through the same gap. The pieces
were tested and the path between them was not: a stylesheet nothing loaded, a
status nothing set, and an upload that wrote its files and never asked for the
grades to be read. Each looked fine in its own test and only showed itself in
use.

So this follows one upload from the zip to what the correction screen is
served. The recognition itself is not run here -- that needs the executor's
image and is covered by its own suite; the executor's half is entered at the
contract the two share, ``rmn_common.auto_grade``, so the boundary is real
rather than mocked.
"""

import io
import json
import os
import time
from zipfile import ZipFile

from rmn_common import auto_grade
from rmn_common.status import Document_Status

JOB = "job-end-to-end"
COPIES = ["Alice_1234567", "Bob_7654321", "Carol_2222222"]

# save_new_pdf_version only copies the file, and the server never parses it:
# what matters on this side is the name, which carries the question.
PDF_BYTES = b"%PDF-1.7\n% not a real pdf, the server only moves it\n%%EOF\n"


def make_job(mongo, question_index=3):
    mongo["eval_jobs"].insert_one(
        {
            "job_id": JOB,
            "user_id": "alice",
            "job_status": "VALIDATION",
            "n_pages_per_question": [["Q3", 2]],
            "n_max_points_per_question": [["Q3", 12]],
            "bonus_enabled_map": [["Q3", False]],
        }
    )
    for index, base in enumerate(COPIES):
        mongo["job_questions"].insert_one(
            {
                "job_id": JOB,
                "document_index": index,
                "question_index": question_index,
                "question": f"Q{question_index}",
                "basename": base,
                "filename": f"{base}_Q{question_index}",
                "rel_filepath": (
                    f"documents/{JOB}/Q{question_index}/{base}_Q{question_index}.pdf"
                ),
                "status": Document_Status.TO_VALIDATE.value,
                "grade": None,
            }
        )
        mongo["job_documents"].insert_one(
            {"job_id": JOB, "document_index": index, "filename": base, "grades": [None]}
        )


def graded_zip():
    """What the pdf-management dialog sends back: one pdf per copy, per question."""
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for base in COPIES:
            archive.writestr(f"{base}_Q3.pdf", PDF_BYTES)
    buffer.seek(0)
    return buffer


def wait_for(predicate, timeout=10.0):
    """The upload is handled on a thread, so the assertions have to wait."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_sending_graded_copies_back_ends_with_the_grades_on_the_screen(
    client, app_module_fixture, login, user_factory
):
    mongo = app_module_fixture.mongo["RMN"]
    storage = app_module_fixture.storage
    redis = app_module_fixture.redis
    user_factory("alice")
    token = login("alice")
    make_job(mongo)

    # --- the teacher sends the graded pdfs back -----------------------------
    # read_grades is deliberately not sent: sending the graded copies back is
    # the whole point, so reading them is what happens unless asked otherwise.
    # The bug this test exists for was the opposite default, with a form that
    # simply left the field out.
    response = client.post(
        "/documents/replace",
        data={
            "job_id": JOB,
            "questions": "true",
            "grades": json.dumps({}),
            "token": token,
            "file": (graded_zip(), "graded.zip"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200

    # --- the pages land where the reader will look for them -----------------
    assert wait_for(
        lambda: all(
            os.path.exists(storage.abs_path(f"documents/{JOB}/Q3/{base}_Q3.pdf"))
            for base in COPIES
        )
    ), "the uploaded pdfs never reached the storage tree"

    # --- and a reading is queued for the question they belong to ------------
    assert wait_for(
        lambda: auto_grade.current_run(mongo["eval_jobs"], JOB, 3) == 1
    ), "the upload wrote its files and never asked for the grades to be read"

    queued = [json.loads(item) for item in redis.lrange("job_queue", 0, -1)]
    reading = [item for item in queued if item.get("read_grades")]
    assert len(reading) == 1
    assert reading[0] == {
        "job_id": JOB,
        "read_grades": True,
        "question_index": 3,
        "run": 1,
    }

    run = reading[0]["run"]
    pending = auto_grade.pending_documents(mongo["job_questions"], JOB, 3, run)
    assert sorted(d["document_index"] for d in pending) == [0, 1, 2]

    # --- the executor reads them (its own suite runs the recogniser) --------
    auto_grade.store_reading(
        mongo["job_questions"], JOB, 0, run, 9.5, 0.97, "ok", "ink", confident=True
    )
    auto_grade.store_reading(
        mongo["job_questions"], JOB, 1, run, 4.0, 0.42, "ambiguous", "ink"
    )
    auto_grade.store_reading(
        mongo["job_questions"], JOB, 2, run, None, 0.0, "not_found", "none"
    )

    # --- what the correction screen is served -------------------------------
    served = client.post(
        "/documents", data={"job_id": JOB, "questions": "true", "token": token}
    ).get_json(force=True)["response"]
    by_index = {d["document_index"]: d for d in served}

    sure = by_index[0]
    assert sure["auto_grade"] == 9.5
    assert sure["auto_grade_confidence"] == 0.97
    # the confidence reaches the teacher as the colour of the box
    assert sure["status"] == Document_Status.HIGH_ACCURACY.value
    assert sure["grade"] is None, "a reading is never a grade until a human says so"

    unsure = by_index[1]
    assert unsure["auto_grade"] == 4.0
    assert unsure["status"] == Document_Status.TO_VALIDATE.value

    blank = by_index[2]
    assert blank["auto_grade"] is None, "an unmarked page must not become a zero"
    assert blank["auto_grade_reason"] == "not_found"


def test_an_upload_that_asks_for_no_reading_queues_none(
    client, app_module_fixture, login, user_factory
):
    """Unticking the box still means what it says."""
    mongo = app_module_fixture.mongo["RMN"]
    storage = app_module_fixture.storage
    user_factory("alice")
    token = login("alice")
    make_job(mongo)

    client.post(
        "/documents/replace",
        data={
            "job_id": JOB,
            "questions": "true",
            "read_grades": "false",
            "grades": json.dumps({}),
            "token": token,
            "file": (graded_zip(), "graded.zip"),
        },
        content_type="multipart/form-data",
    )

    assert wait_for(
        lambda: os.path.exists(
            storage.abs_path(f"documents/{JOB}/Q3/Alice_1234567_Q3.pdf")
        )
    )
    # the files still arrive; nothing is read
    assert auto_grade.current_run(mongo["eval_jobs"], JOB, 3) == 0
    queued = [
        json.loads(i) for i in app_module_fixture.redis.lrange("job_queue", 0, -1)
    ]
    assert not [item for item in queued if item.get("read_grades")]


def test_a_grade_sent_for_one_copy_leaves_the_others_to_be_read(
    client, app_module_fixture, login, user_factory
):
    """A csv covering part of the batch used to call off the whole reading.

    Through the endpoint, not around it: the condition that did this lived in
    the request handler, so a test that called the queueing helper directly
    would not have noticed.
    """
    mongo = app_module_fixture.mongo["RMN"]
    storage = app_module_fixture.storage
    user_factory("alice")
    token = login("alice")
    make_job(mongo)

    client.post(
        "/documents/replace",
        data={
            "job_id": JOB,
            "questions": "true",
            # the teacher's csv knew the grade of the first copy only
            "grades": json.dumps({"0": 11.0}),
            "token": token,
            "file": (graded_zip(), "graded.zip"),
        },
        content_type="multipart/form-data",
    )

    assert wait_for(
        lambda: os.path.exists(
            storage.abs_path(f"documents/{JOB}/Q3/Carol_2222222_Q3.pdf")
        )
    )
    assert wait_for(
        lambda: auto_grade.current_run(mongo["eval_jobs"], JOB, 3) == 1
    ), "one supplied grade called off the reading of the whole upload"

    run = auto_grade.current_run(mongo["eval_jobs"], JOB, 3)
    pending = auto_grade.pending_documents(mongo["job_questions"], JOB, 3, run)
    # the copy the csv graded is left alone, the other two are read
    assert sorted(d["document_index"] for d in pending) == [1, 2]
