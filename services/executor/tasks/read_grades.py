"""Reading the grade a teacher wrote on a re-uploaded question."""

import json
from python.process_copy import auto_grade
from rmn_common.status import Document_Status, Job_Status
from runtime import timestamped_print
from utils.clients import emit_job



# the executor timestamps every line it prints (see runtime.timestamped_print)
print = timestamped_print




def read_grades_for_job(db, storage, sio, job, question_index, run, stopH):
    """Read the grades of one re-uploaded question.

    A thin wrapper: the pass itself lives in ``process_copy.auto_grade``,
    where it can be tested without a redis or a socket. The job status is
    deliberately not touched -- the teacher is correcting and the job stays
    in VALIDATION.
    """
    job_id = job["job_id"]
    user_id = job["user_id"]
    if question_index is None:
        print("read_grades: no question_index in the payload")
        return

    def progress(done, total):
        percent = round(100 * done / total) if total else 100
        emit_job(sio, user_id, job_id, Job_Status(job["job_status"]),
                 infos={"job_infos":
                        f"Lecture des notes de Q{question_index} :"
                        f" {done}/{total} ({percent} %)"})

    # say so before the first page is read: a pass over a few hundred
    # copies is otherwise silent until it is a fifth of the way through,
    # and the teacher has no way to tell it started
    current = db.auto_grade_run(job_id, int(question_index))
    pending = len(
        db.questions_to_read(
            job_id, int(question_index), current if run is None else run
        )
    )
    if pending:
        progress(0, pending)

    def on_read(document_index, reading):
        # one copy, with what it was read as: the correction screen patches
        # that tile instead of refetching every document
        sio.emit("document_ready", json.dumps({
            "job_id": job_id,
            "user_id": user_id,
            "questions": True,
            "question_index": int(question_index),
            "document_index": document_index,
            "auto_grade": reading.grade,
            "auto_grade_confidence": round(float(reading.confidence), 4),
            "auto_grade_reason": reading.reason,
            "auto_grade_source": reading.source,
            **({"status": Document_Status.HIGH_ACCURACY.value} if reading.confident else {}),
        }))

    result = auto_grade.read_question(
        db, storage, job, question_index, run,
        stop=stopH.stop, progress=progress, on_read=on_read,
    )
    print("read_grades: Q%s, %s/%s page(s) read%s" % (
        question_index, result["read"], result["total"],
        ", superseded" if result["superseded"] else ""))

    if result["read"] or pending:
        # the end of the pass: clears the progress line and refetches once
        # (the per-copy events above carry a document_index and are
        # patched in place, this one does not)
        sio.emit("document_ready", json.dumps(
            {"job_id": job_id, "user_id": user_id, "questions": True}))
