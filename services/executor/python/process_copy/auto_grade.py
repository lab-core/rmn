"""One pass of the grade reader over the pages of a single question.

The unit of work is a question, not a job: teachers export, grade and re-upload
one question at a time, and two passes for different questions run side by side
on the executor pods. Each upload is given a run number; every write is
conditional on it, so a pass that a newer upload has superseded stops instead of
storing values it read from files that have since been replaced.

What the pass may touch is deliberately narrow. It writes the ``auto_grade``
fields of ``job_questions`` and nothing else: not ``grade``, which stays the
human's answer, not ``job_documents.grades``, which is what finalisation sums,
and not the job status, because the teacher is in the middle of correcting.

The database and the storage are passed in rather than imported, which is what
lets this be tested against mongomock and a temporary tree.
"""

from typing import Any, Callable, Dict, List, Optional

from process_copy import ink_grades


def question_key(question_index: int) -> str:
    return f"Q{int(question_index)}"


def _points(job: Dict, question_index: int) -> Optional[float]:
    """Maximum of one question, from the job's own configuration."""
    points = dict(job.get("n_max_points_per_question") or [])
    value = points.get(question_key(question_index))
    return float(value) if value is not None else None


def _is_bonus(job: Dict, question_index: int) -> bool:
    return bool(
        dict(job.get("bonus_enabled_map") or []).get(
            question_key(question_index), False
        )
    )


def read_question(
    db: Any,
    storage: Any,
    job: Dict,
    question_index: int,
    run: Optional[int],
    classifier: Any = None,
    open_pdf: Optional[Callable] = None,
    stop: Optional[Callable[[], bool]] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    on_read: Optional[Callable[[int, Any], None]] = None,
) -> Dict[str, int]:
    """Read the grade off every page of one question that is waiting for it.

    Args:
        db: The executor ``Database``.
        storage: The shared storage, for resolving a document's path.
        job: The ``eval_jobs`` row.
        question_index: 1-based question number.
        run: The run number this pass belongs to; ``None`` adopts the current
            one, which is what a manual re-run does.
        classifier: Digit classifier; loaded lazily when a page needs it.
        open_pdf: How to open a file, injected by the tests.
        stop: Called between documents; returning True abandons the pass.
        progress: Called with ``(done, total)`` every few documents.
        on_read: Called with ``(document_index, reading)`` for each reading
            that was stored (not superseded, not a validated document), so the
            correction screen can show it as soon as it is known.

    Returns:
        ``{"read": n, "total": n, "superseded": 0 or 1}``.
    """
    if open_pdf is None:  # pragma: no cover - the executor always has pymupdf
        import pymupdf

        open_pdf = pymupdf.open

    job_id = job["job_id"]
    question_index = int(question_index)
    current = db.auto_grade_run(job_id, question_index)
    if run is None:
        run = current
    if run != current:
        return {"read": 0, "total": 0, "superseded": 1}

    pending = db.questions_to_read(job_id, question_index, run)
    if not pending:
        return {"read": 0, "total": 0, "superseded": 0}

    max_points = _points(job, question_index)
    bonus = _is_bonus(job, question_index)

    # First pass: where this grader puts the grade on this question. Learned
    # from the batch being uploaded, never carried between jobs -- the answer
    # differs between jobs and between questions of the same job.
    candidates: Dict[int, List] = {}
    opened = []
    for document in pending:
        try:
            doc = open_pdf(storage.abs_path(document["rel_filepath"]))
        except Exception as e:
            print("auto_grade: cannot open", document.get("rel_filepath"), e)
            continue
        opened.append(doc)
        candidates[document["document_index"]] = ink_grades.grade_candidates(
            doc[0], max_points
        )

    key = question_key(question_index)
    modal = ink_grades.learn_modal_positions({key: list(candidates.values())}).get(key)

    read = 0
    superseded = 0
    # report about ten times whatever the size: every twentieth copy meant a
    # fifteen-copy pass said nothing at all between starting and finishing
    step = max(1, len(pending) // 10)
    try:
        while True:
            if stop is not None and stop():
                break
            if db.auto_grade_run(job_id, question_index) != run:
                superseded = 1
                break
            claimed = db.claim_question_document(job_id, question_index, run)
            if claimed is None:
                break
            index = claimed["document_index"]
            if index not in candidates:
                db.save_auto_grade(
                    job_id, index, run, ink_grades.Reading(reason="error")
                )
                continue
            if classifier is None:
                from process_copy.classifier import load_classifier

                classifier = load_classifier()
            reading = ink_grades.pick(
                candidates[index], modal, max_points, classifier, bonus
            )
            stored = db.save_auto_grade(job_id, index, run, reading)
            read += 1
            if stored and on_read is not None:
                on_read(index, reading)
            if progress is not None and read % step == 0:
                progress(read, len(pending))
    finally:
        for doc in opened:
            try:
                doc.close()
            except Exception:
                pass

    return {"read": read, "total": len(pending), "superseded": superseded}
