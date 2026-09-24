"""The bookkeeping shared by the two sides of the grade reader.

The server starts a reading pass when a question is re-uploaded; the executor
runs it. Both need the same answer to "which pass is current, which pages does
it still owe, and may this write land", so the rules live here rather than
being written twice and drifting.

A pass belongs to one question, because questions are exported, graded and
re-uploaded one at a time. Each upload bumps that question's run number, and
every write carries it, so a pass a newer upload has overtaken cannot store a
value it read from a file that has since been replaced.

Nothing here writes ``grade`` or ``job_documents.grades``. A read value is a
suggestion until a human confirms it in the correction screen, and
finalisation only ever sums what was confirmed.
"""

from typing import Any, Dict, List, Optional

from pymongo import ReturnDocument

from rmn_common.status import Document_Status

# How a question's readings are judged once a human starts confirming them.
# Questions of one exam are often graded by different people, each with their
# own way of writing a grade, so this is per question and never per job.
MIN_FEEDBACK = 5
MAX_MISMATCH_RATE = 0.4

PENDING = "PENDING"
RUNNING = "RUNNING"
DONE = "DONE"

# fields a reading writes, all namespaced so nothing collides with the grade
FIELDS = (
    "auto_grade",
    "auto_grade_confidence",
    "auto_grade_reason",
    "auto_grade_source",
    "auto_grade_bbox",
    "auto_grade_status",
    "auto_grade_run",
)


def current_run(eval_jobs: Any, job_id: str, question_index: int) -> int:
    """The run number in force for a question, or 0 when none has started."""
    job = eval_jobs.find_one({"job_id": job_id}, {"auto_grade_runs": 1})
    return (job or {}).get("auto_grade_runs", {}).get(str(int(question_index)), 0)


def start_run(
    eval_jobs: Any, job_questions: Any, job_id: str, question_index: int
) -> int:
    """Begin a pass for one question and queue the pages it should read.

    Documents a human has already validated are left out: re-uploading a
    question must not disturb a grade someone confirmed.

    Returns:
        The new run number.
    """
    question_index = int(question_index)
    job = eval_jobs.find_one_and_update(
        {"job_id": job_id},
        {"$inc": {f"auto_grade_runs.{question_index}": 1}},
        return_document=ReturnDocument.AFTER,
    )
    run = (job or {}).get("auto_grade_runs", {}).get(str(question_index), 1)
    job_questions.update_many(
        {
            "job_id": job_id,
            "question_index": question_index,
            "status": {"$ne": Document_Status.VALIDATED.value},
            "grade": None,
        },
        {"$set": {"auto_grade_status": PENDING, "auto_grade_run": run}},
    )
    return run


def pending_documents(
    job_questions: Any, job_id: str, question_index: int, run: int
) -> List[Dict]:
    """Pages of a question still waiting for this pass."""
    return list(
        job_questions.find(
            {
                "job_id": job_id,
                "question_index": int(question_index),
                "auto_grade_status": PENDING,
                "auto_grade_run": run,
            }
        )
    )


def claim_document(
    job_questions: Any, job_id: str, question_index: int, run: int
) -> Optional[Dict]:
    """Take the next page of the question, atomically.

    Two executor pods can be working the same question; the claim is what
    keeps them off the same page.
    """
    return job_questions.find_one_and_update(
        {
            "job_id": job_id,
            "question_index": int(question_index),
            "auto_grade_status": PENDING,
            "auto_grade_run": run,
        },
        {"$set": {"auto_grade_status": RUNNING}},
        return_document=ReturnDocument.AFTER,
    )


def store_reading(
    job_questions: Any,
    job_id: str,
    document_index: int,
    run: int,
    grade: Optional[float],
    confidence: float,
    reason: str,
    source: str,
    bbox: Optional[List[float]] = None,
    confident: bool = False,
) -> bool:
    """Record what a page was read as, if the pass may still speak for it.

    A confident reading also moves the document to ``HIGH_ACCURACY``, which is
    what the rest of the app already means by "the machine read this and the
    teacher should glance at it" -- the copy tiles, the validate button and the
    score box all colour it blue, against red for one still to be worked out.
    Without it every copy stayed ``TO_VALIDATE`` and the confidence was
    invisible.

    Args:
        confident: Whether the caller considers the reading good enough to
            offer as more than a guess; the threshold lives with the reader.

    Returns:
        True when the reading was stored; False when the pass has been
        superseded or the document has meanwhile been validated by a human.
    """
    result = job_questions.update_one(
        {
            "job_id": job_id,
            "document_index": document_index,
            "auto_grade_run": run,
            "status": {"$ne": Document_Status.VALIDATED.value},
        },
        {
            "$set": {
                "auto_grade": grade,
                "auto_grade_confidence": round(float(confidence), 4),
                "auto_grade_reason": reason,
                "auto_grade_source": source,
                "auto_grade_bbox": list(bbox) if bbox else None,
                "auto_grade_status": DONE,
                **(
                    {"status": Document_Status.HIGH_ACCURACY.value} if confident else {}
                ),
            }
        },
    )
    return result.modified_count == 1


def projection(document: Dict) -> Dict:
    """The reading fields as the webapp receives them.

    ``get`` throughout: documents created before this feature have none of
    these keys, and the correction screen must keep working for them.
    """
    return {
        "auto_grade": document.get("auto_grade"),
        "auto_grade_confidence": document.get("auto_grade_confidence"),
        "auto_grade_reason": document.get("auto_grade_reason"),
        "auto_grade_source": document.get("auto_grade_source"),
        # PENDING/RUNNING/DONE, so the correction screen can say which copies
        # the reader has not reached yet
        "auto_grade_status": document.get("auto_grade_status"),
    }


def feedback(job_questions: Any, job_id: str, question_index: int):
    """How the readings of one question compare with the grades humans gave.

    Only documents a human has already validated count, and only those the
    reader had offered a value for: everything else says nothing either way.

    Returns:
        ``(confirmed, mismatched)``.
    """
    judged = list(
        job_questions.find(
            {
                "job_id": job_id,
                "question_index": int(question_index),
                "grade": {"$ne": None},
                "auto_grade": {"$ne": None},
            },
            {"grade": 1, "auto_grade": 1},
        )
    )
    mismatched = sum(
        1 for d in judged if abs(float(d["grade"]) - float(d["auto_grade"])) > 1e-6
    )
    return len(judged), mismatched


def unreliable(job_questions: Any, job_id: str, question_index: int) -> bool:
    """True when this question's readings have been wrong too often.

    A few disagreements are ordinary -- a teacher overrides a grade, a digit is
    genuinely ambiguous. A steady stream of them means the reader has the wrong
    idea of how this question was graded, and every remaining suggestion is
    likely wrong in the same way.
    """
    confirmed, mismatched = feedback(job_questions, job_id, question_index)
    return confirmed >= MIN_FEEDBACK and mismatched / confirmed > MAX_MISMATCH_RATE


def distrust_suggestions(job_questions: Any, job_id: str, question_index: int) -> int:
    """Stop vouching for a question's readings, without discarding them.

    The readings are kept: on the batch this was measured against, the right
    answer is still the reader's own top answer about two thirds of the time,
    so throwing them away would cost the teacher more typing than it saves.
    What goes is the claim that they are right -- the copies drop back to
    TO_VALIDATE, so the screen shows them red and unconfirmed instead of blue,
    and nothing is offered as settled.

    Confirmed grades are untouched: they are the human's.

    Returns:
        How many copies stopped being vouched for.
    """
    result = job_questions.update_many(
        {
            "job_id": job_id,
            "question_index": int(question_index),
            "grade": None,
            "auto_grade": {"$ne": None},
            "status": Document_Status.HIGH_ACCURACY.value,
        },
        {
            "$set": {
                "auto_grade_reason": "unreliable",
                "status": Document_Status.TO_VALIDATE.value,
            }
        },
    )
    return result.modified_count


def queue_document(
    eval_jobs: Any,
    job_questions: Any,
    job_id: str,
    question_index: int,
    document_index: int,
) -> Optional[int]:
    """Ask for one page to be read, without touching the rest of its question.

    Grading inside the app saves one copy at a time, and re-reading a whole
    question on every save would be absurd. The run is left where it is: this
    joins the pass that is current rather than starting a new one.

    Returns:
        The run it was queued under, or ``None`` if the copy already has a
        grade and there is nothing to read.
    """
    question_index = int(question_index)
    run = current_run(eval_jobs, job_id, question_index)
    if not run:
        run = 1
        eval_jobs.update_one(
            {"job_id": job_id},
            {"$set": {f"auto_grade_runs.{question_index}": run}},
        )
    result = job_questions.update_one(
        {
            "job_id": job_id,
            "document_index": document_index,
            "grade": None,
            "status": {"$ne": Document_Status.VALIDATED.value},
        },
        {"$set": {"auto_grade_status": PENDING, "auto_grade_run": run}},
    )
    return run if result.modified_count else None


def progress(job_questions: Any, job_id: str) -> Dict[str, Dict[str, int]]:
    """How far the reading has got, question by question.

    Derived from the documents themselves rather than kept as a counter: a
    pass can be superseded, abandoned or run by either of two pods, and a
    counter would have to be right about all of that. The documents already
    say.

    Returns:
        ``{question_index: {"pending": n, "running": n, "done": n, "total": n}}``
        for the questions a reading has touched. A question with pages still
        pending or running is one the teacher is waiting on.
    """
    counts: Dict[str, Dict[str, int]] = {}
    for row in job_questions.find(
        {"job_id": job_id, "auto_grade_status": {"$exists": True}},
        {"question_index": 1, "auto_grade_status": 1},
    ):
        question = str(row.get("question_index"))
        state = (row.get("auto_grade_status") or "").lower()
        entry = counts.setdefault(
            question, {"pending": 0, "running": 0, "done": 0, "total": 0}
        )
        entry["total"] += 1
        if state in entry:
            entry[state] += 1
    return counts


def is_running(job_questions: Any, job_id: str) -> bool:
    """Whether any question of this job still has pages waiting to be read."""
    return bool(
        job_questions.find_one(
            {"job_id": job_id, "auto_grade_status": {"$in": [PENDING, RUNNING]}},
            {"_id": 1},
        )
    )
