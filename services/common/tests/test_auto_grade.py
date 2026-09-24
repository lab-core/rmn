"""The grade reader's bookkeeping: runs, claims, readings and how far it got.

The functions only talk to two Mongo collections, so they run here against a
small in-memory stand-in implementing the handful of operators they use;
mongomock is a dependency of the server, not of this package.
"""

import copy
import sys
import types

try:
    import pymongo  # noqa: F401  (auto_grade only needs ReturnDocument)
except ImportError:  # the package declares no dependency: stub the constant
    sys.modules["pymongo"] = types.SimpleNamespace(
        ReturnDocument=types.SimpleNamespace(BEFORE=False, AFTER=True)
    )

import pytest

from rmn_common import auto_grade
from rmn_common.auto_grade import DONE, PENDING, RUNNING

_MISSING = object()


def _matches(doc, query):
    for key, cond in query.items():
        value = doc.get(key, _MISSING)
        if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
            for op, arg in cond.items():
                present = None if value is _MISSING else value
                if op == "$ne" and present == arg:
                    return False
                if op == "$in" and present not in arg:
                    return False
                if op == "$gt" and (present is None or not present > arg):
                    return False
        elif cond is None:
            if value not in (None, _MISSING):
                return False
        elif value != cond:
            return False
    return True


def _apply(doc, update):
    for op, fields in update.items():
        for dotted, arg in fields.items():
            *parents, leaf = dotted.split(".")
            target = doc
            for part in parents:
                target = target.setdefault(part, {})
            if op == "$set":
                target[leaf] = arg
            elif op == "$inc":
                target[leaf] = target.get(leaf, 0) + arg
            else:
                raise NotImplementedError(op)


class FakeCollection:
    """Just enough of a pymongo collection for ``auto_grade``."""

    def __init__(self, docs=()):
        self.docs = [{"_id": i, **d} for i, d in enumerate(docs)]

    def _project(self, doc, projection):
        if not projection:
            return copy.deepcopy(doc)
        # like Mongo, the _id comes along unless excluded
        keys = {"_id", *projection}
        return {k: copy.deepcopy(doc[k]) for k in keys if k in doc}

    def find(self, query, projection=None):
        return [self._project(d, projection) for d in self.docs if _matches(d, query)]

    def find_one(self, query, projection=None):
        found = self.find(query, projection)
        return found[0] if found else None

    def _update(self, query, update, many):
        matched = modified = 0
        for doc in self.docs:
            if _matches(doc, query):
                matched += 1
                before = copy.deepcopy(doc)
                _apply(doc, update)
                modified += doc != before
                if not many:
                    break
        return types.SimpleNamespace(matched_count=matched, modified_count=modified)

    def update_one(self, query, update):
        return self._update(query, update, many=False)

    def update_many(self, query, update):
        return self._update(query, update, many=True)

    def find_one_and_update(self, query, update, return_document=False):
        for doc in self.docs:
            if _matches(doc, query):
                before = copy.deepcopy(doc)
                _apply(doc, update)
                return copy.deepcopy(doc) if return_document else before
        return None


def _question(index, question_index=1, **extra):
    doc = {
        "job_id": "j",
        "document_index": index,
        "question_index": question_index,
        "status": "TO VALIDATE",
        "grade": None,
    }
    doc.update(extra)
    return doc


@pytest.fixture
def eval_jobs():
    return FakeCollection([{"job_id": "j"}])


def _doc(questions, index):
    return questions.find_one({"document_index": index})


# ------------------------------------------------------------------ runs ---
def test_there_is_no_run_before_the_first_upload(eval_jobs):
    assert auto_grade.current_run(eval_jobs, "j", 1) == 0
    assert auto_grade.current_run(eval_jobs, "unknown", 1) == 0


def test_each_upload_starts_a_new_run_of_its_own_question(eval_jobs):
    questions = FakeCollection()
    assert auto_grade.start_run(eval_jobs, questions, "j", 1) == 1
    assert auto_grade.start_run(eval_jobs, questions, "j", "1") == 2
    assert auto_grade.start_run(eval_jobs, questions, "j", 2) == 1
    assert auto_grade.current_run(eval_jobs, "j", 1) == 2
    assert auto_grade.current_run(eval_jobs, "j", 2) == 1


def test_a_run_queues_only_the_pages_nobody_has_graded(eval_jobs):
    questions = FakeCollection(
        [
            _question(0),
            _question(1, status="VALIDATED"),
            _question(2, grade=3.0),
            _question(3, question_index=2),
        ]
    )
    run = auto_grade.start_run(eval_jobs, questions, "j", 1)

    assert [
        d["document_index"]
        for d in auto_grade.pending_documents(questions, "j", 1, run)
    ] == [0]
    assert "auto_grade_status" not in _doc(questions, 1)
    assert "auto_grade_status" not in _doc(questions, 2)
    assert "auto_grade_status" not in _doc(questions, 3)


def test_a_page_is_claimed_once_and_only_by_the_current_run(eval_jobs):
    questions = FakeCollection([_question(0), _question(1)])
    run = auto_grade.start_run(eval_jobs, questions, "j", 1)

    assert auto_grade.claim_document(questions, "j", 1, run - 1) is None
    first = auto_grade.claim_document(questions, "j", 1, run)
    second = auto_grade.claim_document(questions, "j", 1, run)
    assert first["auto_grade_status"] == RUNNING
    assert {first["document_index"], second["document_index"]} == {0, 1}
    assert auto_grade.claim_document(questions, "j", 1, run) is None
    assert auto_grade.pending_documents(questions, "j", 1, run) == []


# -------------------------------------------------------------- readings ---
def test_a_confident_reading_is_stored_and_shown_as_high_accuracy(eval_jobs):
    questions = FakeCollection([_question(0)])
    run = auto_grade.start_run(eval_jobs, questions, "j", 1)

    stored = auto_grade.store_reading(
        questions,
        "j",
        0,
        run,
        4.5,
        0.912345,
        "digits",
        "ocr",
        bbox=(1, 2, 3, 4),
        confident=True,
    )

    assert stored is True
    doc = _doc(questions, 0)
    assert doc["auto_grade"] == 4.5 and doc["auto_grade_confidence"] == 0.9123
    assert doc["auto_grade_bbox"] == [1, 2, 3, 4]
    assert (doc["auto_grade_status"], doc["status"]) == (DONE, "HIGH ACCURACY")
    # a reading is a suggestion: the grade stays the human's to give
    assert doc["grade"] is None


def test_an_unsure_reading_leaves_the_status(eval_jobs):
    questions = FakeCollection([_question(0)])
    run = auto_grade.start_run(eval_jobs, questions, "j", 1)
    assert auto_grade.store_reading(questions, "j", 0, run, None, 0.1, "blank", "ocr")
    doc = _doc(questions, 0)
    assert doc["status"] == "TO VALIDATE" and doc["auto_grade_bbox"] is None


def test_a_superseded_run_cannot_store_its_reading(eval_jobs):
    questions = FakeCollection([_question(0)])
    old = auto_grade.start_run(eval_jobs, questions, "j", 1)
    auto_grade.start_run(eval_jobs, questions, "j", 1)
    assert auto_grade.store_reading(questions, "j", 0, old, 2, 0.9, "d", "ocr") is False
    assert "auto_grade" not in _doc(questions, 0)


def test_a_reading_never_overwrites_a_validated_copy(eval_jobs):
    questions = FakeCollection([_question(0)])
    run = auto_grade.start_run(eval_jobs, questions, "j", 1)
    questions.update_one({"document_index": 0}, {"$set": {"status": "VALIDATED"}})
    assert auto_grade.store_reading(questions, "j", 0, run, 2, 0.9, "d", "ocr") is False
    assert _doc(questions, 0)["status"] == "VALIDATED"


def test_projection_tolerates_documents_older_than_the_reader():
    assert auto_grade.projection({"grade": 3}) == {
        "auto_grade": None,
        "auto_grade_confidence": None,
        "auto_grade_reason": None,
        "auto_grade_source": None,
        "auto_grade_status": None,
    }


# ---------------------------------------------------------------- trust ---
def _judged(pairs):
    """Copies a human graded, with what the reader had suggested for each."""
    return [
        _question(i, grade=grade, auto_grade=read, status="VALIDATED")
        for i, (grade, read) in enumerate(pairs)
    ]


def test_feedback_counts_only_copies_both_read_and_graded():
    questions = FakeCollection(
        _judged([(1, 1), (2, 3)])
        + [_question(10, auto_grade=4), _question(11, grade=5)]
    )
    assert auto_grade.feedback(questions, "j", 1) == (2, 1)


def test_a_few_disagreements_are_not_enough_to_distrust_a_question():
    # 3 of 4 wrong, but 4 is below MIN_FEEDBACK
    questions = FakeCollection(_judged([(1, 2), (1, 3), (1, 4), (1, 1)]))
    assert not auto_grade.unreliable(questions, "j", 1)


def test_a_question_read_wrong_too_often_is_unreliable():
    questions = FakeCollection(_judged([(1, 2), (1, 3), (1, 1), (1, 1), (1, 4)]))
    assert auto_grade.unreliable(questions, "j", 1)
    # 2 wrong out of 5 is at the rate, not above it
    questions = FakeCollection(_judged([(1, 2), (1, 3), (1, 1), (1, 1), (1, 1)]))
    assert not auto_grade.unreliable(questions, "j", 1)


def test_distrust_drops_the_confident_suggestions_but_keeps_them():
    questions = FakeCollection(
        [
            _question(0, auto_grade=3, status="HIGH ACCURACY"),
            _question(1, auto_grade=3, status="HIGH ACCURACY", grade=3),
            _question(2, auto_grade=3, status="TO VALIDATE"),
            _question(3, auto_grade=3, status="HIGH ACCURACY", question_index=2),
        ]
    )

    assert auto_grade.distrust_suggestions(questions, "j", 1) == 1

    doc = _doc(questions, 0)
    assert (doc["status"], doc["auto_grade"], doc["auto_grade_reason"]) == (
        "TO VALIDATE",
        3,
        "unreliable",
    )
    assert _doc(questions, 1)["status"] == "HIGH ACCURACY"  # the human's grade
    assert _doc(questions, 3)["status"] == "HIGH ACCURACY"  # another question


# ----------------------------------------------------- one copy at a time ---
def test_queueing_a_copy_starts_the_first_run_if_there_is_none(eval_jobs):
    questions = FakeCollection([_question(0)])
    assert auto_grade.queue_document(eval_jobs, questions, "j", 1, 0) == 1
    assert auto_grade.current_run(eval_jobs, "j", 1) == 1
    assert _doc(questions, 0)["auto_grade_status"] == PENDING


def test_queueing_a_copy_joins_the_current_run(eval_jobs):
    questions = FakeCollection([_question(0), _question(1)])
    auto_grade.start_run(eval_jobs, questions, "j", 1)
    auto_grade.start_run(eval_jobs, questions, "j", 1)
    questions.update_one({"document_index": 1}, {"$set": {"auto_grade_status": DONE}})

    assert auto_grade.queue_document(eval_jobs, questions, "j", "1", 1) == 2
    assert auto_grade.current_run(eval_jobs, "j", 1) == 2
    assert _doc(questions, 1)["auto_grade_status"] == PENDING


def test_a_graded_copy_is_not_queued(eval_jobs):
    questions = FakeCollection(
        [_question(0, grade=2), _question(1, status="VALIDATED")]
    )
    assert auto_grade.queue_document(eval_jobs, questions, "j", 1, 0) is None
    assert auto_grade.queue_document(eval_jobs, questions, "j", 1, 1) is None


# --------------------------------------------------------------- progress ---
def test_progress_counts_every_copy_of_the_questions_being_read():
    questions = FakeCollection(
        [
            _question(0, auto_grade_status=PENDING),
            _question(1, auto_grade_status=RUNNING),
            _question(2, auto_grade_status=DONE),
            _question(3, auto_grade_status=DONE, grade=2),  # graded meanwhile
            _question(4),  # never given to the reader
            _question(5, question_index=2),  # a question no pass touched
            _question(6, question_index=3, grade=1),
        ]
    )
    assert auto_grade.progress(questions, "j") == {
        "1": {"pending": 1, "running": 1, "done": 1, "graded": 1, "total": 5}
    }


def test_is_running_while_a_page_is_pending_or_claimed():
    assert not auto_grade.is_running(
        FakeCollection([_question(0, auto_grade_status=DONE)]), "j"
    )
    assert auto_grade.is_running(
        FakeCollection([_question(0, auto_grade_status=RUNNING)]), "j"
    )
    assert auto_grade.is_running(
        FakeCollection([_question(0, auto_grade_status=PENDING)]), "j"
    )
    assert not auto_grade.is_running(
        FakeCollection([_question(0, auto_grade_status=PENDING)]), "k"
    )
