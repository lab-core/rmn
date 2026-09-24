"""The bookkeeping around a reading pass: supersede, claim, and what it writes.

Questions are uploaded separately and their passes run at the same time, so a
pass has to know whether it is still the current one, two pods have to not read
the same page twice, and neither may touch a grade a human already confirmed.
"""

import pytest

from python.process_copy.database import Database
from python.process_copy.ink_grades import Reading
from rmn_common.status import Document_Status

JOB = "job-under-test"


@pytest.fixture
def db():
    database = Database()
    database.eval_jobs_collection().insert_one({"job_id": JOB, "user_id": "alice"})
    return database


def add_question(db, document_index, question_index=3, status=None, grade=None):
    db.questions_collection().insert_one(
        {
            "job_id": JOB,
            "document_index": document_index,
            "question_index": question_index,
            "question": f"Q{question_index}",
            "rel_filepath": (
                f"documents/{JOB}/Q{question_index}/copy{document_index}.pdf"
            ),
            "status": (status or Document_Status.TO_VALIDATE).value,
            "grade": grade,
        }
    )


def reading(grade=7.5, confidence=0.97):
    return Reading(
        grade=grade,
        confidence=confidence,
        reason="ok",
        source="ink",
        bbox=(1.0, 2.0, 3.0, 4.0),
        n_candidates=1,
    )


def test_a_new_upload_starts_a_run_and_queues_its_documents(db):
    add_question(db, 0)
    add_question(db, 1)

    run = db.bump_auto_grade_run(JOB, 3)

    assert run == 1
    assert db.auto_grade_run(JOB, 3) == 1
    assert len(db.questions_to_read(JOB, 3, run)) == 2


def test_a_confirmed_grade_is_left_out_of_the_pass(db):
    """Re-uploading a question must not disturb what someone already validated."""
    add_question(db, 0)
    add_question(db, 1, status=Document_Status.VALIDATED, grade=8.0)

    run = db.bump_auto_grade_run(JOB, 3)
    queued = [doc["document_index"] for doc in db.questions_to_read(JOB, 3, run)]

    assert queued == [0]


def test_a_document_is_claimed_once(db):
    """Two pods share a question; the claim is what keeps them off one page."""
    add_question(db, 0)
    run = db.bump_auto_grade_run(JOB, 3)

    first = db.claim_question_document(JOB, 3, run)
    second = db.claim_question_document(JOB, 3, run)

    assert first["document_index"] == 0
    assert second is None


def test_a_superseded_pass_cannot_write(db):
    """The page it read has been replaced, so its answer is about a stale file."""
    add_question(db, 0)
    stale = db.bump_auto_grade_run(JOB, 3)
    db.claim_question_document(JOB, 3, stale)
    current = db.bump_auto_grade_run(JOB, 3)

    assert current == stale + 1
    assert db.save_auto_grade(JOB, 0, stale, reading()) is False
    stored = db.questions_collection().find_one({"job_id": JOB, "document_index": 0})
    assert stored.get("auto_grade") is None


def test_a_reading_never_overwrites_a_validated_document(db):
    add_question(db, 0)
    run = db.bump_auto_grade_run(JOB, 3)
    db.questions_collection().update_one(
        {"job_id": JOB, "document_index": 0},
        {"$set": {"status": Document_Status.VALIDATED.value, "grade": 6.0}},
    )

    assert db.save_auto_grade(JOB, 0, run, reading()) is False
    stored = db.questions_collection().find_one({"job_id": JOB, "document_index": 0})
    assert stored["grade"] == 6.0
    assert stored.get("auto_grade") is None


def test_a_reading_is_stored_beside_the_grade_not_in_it(db):
    """``grade`` stays the human's answer; finalisation sums only confirmed ones."""
    add_question(db, 0)
    run = db.bump_auto_grade_run(JOB, 3)

    assert db.save_auto_grade(JOB, 0, run, reading()) is True

    stored = db.questions_collection().find_one({"job_id": JOB, "document_index": 0})
    assert stored["auto_grade"] == 7.5
    assert stored["auto_grade_confidence"] == 0.97
    assert stored["auto_grade_source"] == "ink"
    assert stored["auto_grade_status"] == "DONE"
    assert stored["grade"] is None


def test_a_confident_reading_shows_as_high_accuracy(db):
    """The status is how the confidence reaches the screen.

    The tiles, the validate button and the score box all colour HIGH_ACCURACY
    blue and TO_VALIDATE red. Writing only the auto_grade fields left every
    copy red however sure the reader was.
    """
    add_question(db, 0)
    add_question(db, 1)
    run = db.bump_auto_grade_run(JOB, 3)

    db.save_auto_grade(JOB, 0, run, reading(confidence=0.97))
    db.save_auto_grade(JOB, 1, run, reading(confidence=0.4))

    sure = db.questions_collection().find_one({"job_id": JOB, "document_index": 0})
    unsure = db.questions_collection().find_one({"job_id": JOB, "document_index": 1})
    assert sure["status"] == Document_Status.HIGH_ACCURACY.value
    assert unsure["status"] == Document_Status.TO_VALIDATE.value
    # neither is a grade until a human says so
    assert sure["grade"] is None and unsure["grade"] is None


def test_nothing_found_is_recorded_as_nothing(db):
    """A page with no mark must not come back as a confident zero."""
    add_question(db, 0)
    run = db.bump_auto_grade_run(JOB, 3)

    db.save_auto_grade(JOB, 0, run, Reading(reason="not_found"))

    stored = db.questions_collection().find_one({"job_id": JOB, "document_index": 0})
    assert stored["auto_grade"] is None
    assert stored["auto_grade_reason"] == "not_found"


def test_runs_of_different_questions_do_not_interfere(db):
    """Two questions are uploaded separately and advance on their own."""
    add_question(db, 0, question_index=3)
    add_question(db, 1, question_index=5)

    run_three = db.bump_auto_grade_run(JOB, 3)
    db.bump_auto_grade_run(JOB, 5)
    db.bump_auto_grade_run(JOB, 5)

    assert run_three == 1
    assert db.auto_grade_run(JOB, 3) == 1
    assert db.auto_grade_run(JOB, 5) == 2
    assert db.save_auto_grade(JOB, 0, run_three, reading()) is True


# ---------------------------------------------------------------- one pass --
def _job_row(db):
    return db.eval_jobs_collection().find_one({"job_id": JOB})


@pytest.fixture
def graded_question(db, tmp_path):
    """Three real graded pages of one question, staged where storage expects."""
    import json
    import os
    import shutil

    fixtures = os.path.join(os.path.dirname(__file__), "fixtures", "ink_grades")
    spec = json.load(open(os.path.join(fixtures, "expected.json")))["fixtures"]
    chosen = [
        entry
        for entry in spec
        if entry["file"]
        in (
            "ink_circled_single.pdf",
            "ink_two_digit.pdf",
            "ink_no_annotation.pdf",
        )
    ]
    target = tmp_path / "documents" / JOB / "Q3"
    target.mkdir(parents=True)
    for index, entry in enumerate(chosen):
        shutil.copy(os.path.join(fixtures, entry["file"]), target / entry["file"])
        db.questions_collection().insert_one(
            {
                "job_id": JOB,
                "document_index": index,
                "question_index": 3,
                "question": "Q3",
                "rel_filepath": f"documents/{JOB}/Q3/{entry['file']}",
                "status": Document_Status.TO_VALIDATE.value,
                "grade": None,
            }
        )
    db.eval_jobs_collection().update_one(
        {"job_id": JOB},
        {
            "$set": {
                "job_status": "VALIDATION",
                "n_max_points_per_question": [["Q3", 12]],
                "bonus_enabled_map": [["Q3", False]],
            }
        },
    )
    return chosen, tmp_path


def test_a_pass_reads_every_pending_page_and_touches_nothing_else(db, graded_question):
    import pymupdf

    from process_copy import auto_grade
    from utils.storage import Storage

    chosen, root = graded_question
    storage = Storage(str(root))
    run = db.bump_auto_grade_run(JOB, 3)

    result = auto_grade.read_question(
        db, storage, _job_row(db), 3, run, open_pdf=pymupdf.open
    )

    assert result == {"read": 3, "total": 3, "superseded": 0}
    for index, entry in enumerate(chosen):
        stored = db.questions_collection().find_one(
            {"job_id": JOB, "document_index": index}
        )
        assert stored["auto_grade"] == entry["expected"], entry["file"]
        # the human's field and the array finalisation sums are untouched
        assert stored["grade"] is None
        assert stored["status"] == Document_Status.TO_VALIDATE.value
    assert _job_row(db)["job_status"] == "VALIDATION"
    assert db.documents_collection().count_documents({"job_id": JOB}) == 0


def test_a_pass_stops_when_a_newer_upload_arrives(db, graded_question):
    import pymupdf

    from process_copy import auto_grade
    from utils.storage import Storage

    _, root = graded_question
    stale = db.bump_auto_grade_run(JOB, 3)
    db.bump_auto_grade_run(JOB, 3)  # the teacher re-uploads mid-pass

    result = auto_grade.read_question(
        db, Storage(str(root)), _job_row(db), 3, stale, open_pdf=pymupdf.open
    )

    assert result["superseded"] == 1
    assert result["read"] == 0


def test_a_pass_can_be_abandoned(db, graded_question):
    """``stop`` is how a deleted job ends a pass that is already running."""
    import pymupdf

    from process_copy import auto_grade
    from utils.storage import Storage

    _, root = graded_question
    run = db.bump_auto_grade_run(JOB, 3)

    result = auto_grade.read_question(
        db,
        Storage(str(root)),
        _job_row(db),
        3,
        run,
        open_pdf=pymupdf.open,
        stop=lambda: True,
    )

    assert result["read"] == 0


# ------------------------------------------- when the readings prove wrong --
def test_a_question_whose_readings_keep_missing_stops_being_trusted(db):
    """Different people grade different questions, each writing grades their
    own way, so a question the reader has misjudged keeps misjudging it.

    The readings stay -- measured on a real batch, the right answer is still
    the reader's own top answer about two thirds of the time, so discarding
    them costs the teacher more typing than it saves. What goes is the claim
    that they are right.
    """
    from rmn_common import auto_grade

    for index in range(8):
        add_question(db, index)
    run = db.bump_auto_grade_run(JOB, 3)
    for index in range(8):
        db.save_auto_grade(JOB, index, run, reading(grade=7.5))

    questions = db.questions_collection()
    # five copies confirmed, four of them not what the reader said
    for index, human in enumerate([2.0, 3.0, 4.0, 5.0, 7.5]):
        questions.update_one(
            {"job_id": JOB, "document_index": index}, {"$set": {"grade": human}}
        )

    confirmed, mismatched = auto_grade.feedback(questions, JOB, 3)
    assert (confirmed, mismatched) == (5, 4)
    assert auto_grade.unreliable(questions, JOB, 3)

    distrusted = auto_grade.distrust_suggestions(questions, JOB, 3)

    assert distrusted == 3  # the three nobody has confirmed yet
    for index in range(5):
        kept = questions.find_one({"job_id": JOB, "document_index": index})
        assert kept["grade"] is not None  # the human's answers are untouched
    for index in range(5, 8):
        doubted = questions.find_one({"job_id": JOB, "document_index": index})
        assert doubted["auto_grade"] == 7.5  # still offered
        assert doubted["auto_grade_reason"] == "unreliable"
        assert doubted["status"] == Document_Status.TO_VALIDATE.value  # not blue


def test_a_question_the_reader_gets_right_keeps_its_suggestions(db):
    from rmn_common import auto_grade

    for index in range(6):
        add_question(db, index)
    run = db.bump_auto_grade_run(JOB, 3)
    for index in range(6):
        db.save_auto_grade(JOB, index, run, reading(grade=7.5))
    questions = db.questions_collection()
    for index in range(5):
        questions.update_one(
            {"job_id": JOB, "document_index": index}, {"$set": {"grade": 7.5}}
        )

    assert auto_grade.feedback(questions, JOB, 3) == (5, 0)
    assert not auto_grade.unreliable(questions, JOB, 3)


def test_a_couple_of_disagreements_are_not_enough(db):
    """A teacher overriding a grade is ordinary; only a pattern counts."""
    from rmn_common import auto_grade

    for index in range(3):
        add_question(db, index)
    run = db.bump_auto_grade_run(JOB, 3)
    for index in range(3):
        db.save_auto_grade(JOB, index, run, reading(grade=7.5))
    questions = db.questions_collection()
    for index in range(3):
        questions.update_one(
            {"job_id": JOB, "document_index": index}, {"$set": {"grade": 1.0}}
        )

    # all three disagree, but three is below the minimum to judge on
    assert auto_grade.feedback(questions, JOB, 3) == (3, 3)
    assert not auto_grade.unreliable(questions, JOB, 3)
