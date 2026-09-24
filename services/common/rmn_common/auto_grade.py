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
) -> bool:
    """Record what a page was read as, if the pass may still speak for it.

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
    }
