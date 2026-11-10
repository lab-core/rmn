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

from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from process_copy import digit_bank, ink_grades
from rmn_common.status import Document_Status


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


def _learn_question(
    db: Any,
    storage: Any,
    job_id: str,
    question_index: int,
    max_points: Optional[float],
    open_pdf: Callable,
    keep: Set[int],
) -> Tuple[Dict[int, List], List, Any]:
    """The candidates of a question's pages, and where its graders write.

    Where the grade sits is learned from every page of the question that
    carries marks, not only the pages about to be read: a copy graded in the
    app is read alone, and from one page nothing can be learned (its reading
    stayed capped at 50 %). Never carried between jobs -- the answer differs
    between jobs and between questions of the same job.

    Args:
        db: The executor ``Database``.
        storage: The storage the pages are read from.
        job_id: The job.
        question_index: 1-based question number.
        max_points: The question's maximum.
        open_pdf: How to open a file.
        keep: The documents whose candidates are wanted; their pdfs stay
            open for the caller to close.

    Returns:
        ``(candidates by document index, open pdfs, learned positions)``.
    """
    candidates: Dict[int, List] = {}
    learning: List = []
    opened = []
    for document in db.question_documents(job_id, question_index):
        index = document["document_index"]
        try:
            doc = open_pdf(storage.abs_path(document["rel_filepath"]))
        except Exception as e:
            print("auto_grade: cannot open", document.get("rel_filepath"), e)
            continue
        page_candidates = ink_grades.grade_candidates(doc[0], max_points)
        learning.append(page_candidates)
        if index in keep:
            opened.append(doc)
            candidates[index] = page_candidates
        else:
            doc.close()

    key = question_key(question_index)
    modal = ink_grades.learn_modal_positions({key: learning}).get(key)
    return candidates, opened, modal


def restage_question(
    db: Any,
    storage: Any,
    job: Dict,
    question_index: int,
    classifier: Any,
    bank_storage: Any = None,
    open_pdf: Optional[Callable] = None,
) -> Dict[str, int]:
    """Read a question's confirmed pages again, only to stage their digits.

    For rebuilding the digit bank of a job read by an older reader
    (``tools/build_digit_bank.py rebuild``): the pages a human gave a grade
    are read with the reader as it is now, and each reading is staged the way
    a read pass stages it, for ``digit_bank.promote_job`` to label with that
    grade. Nothing is written to the database -- not ``auto_grade``, and
    certainly not the grade.

    Args:
        db: The executor ``Database``.
        storage: The storage the pages are read from.
        job: The ``eval_jobs`` row.
        question_index: 1-based question number.
        classifier: The digit classifier.
        bank_storage: Where to stage; ``storage`` by default. A dry run
            stages into a throwaway tree.
        open_pdf: How to open a file, injected by the tests.

    Returns:
        ``{"pages": read, "staged": kept for the bank}``.
    """
    if open_pdf is None:  # pragma: no cover - the executor always has pymupdf
        import pymupdf

        open_pdf = pymupdf.open

    job_id = job["job_id"]
    question_index = int(question_index)
    deleted = {
        d["document_index"]
        for d in db.documents_collection().find(
            {"job_id": job_id, "status": Document_Status.DELETED.value},
            {"document_index": 1},
        )
    }
    grades = {
        q["document_index"]: float(q["grade"])
        for q in db.questions_collection().find(
            {
                "job_id": job_id,
                "question_index": question_index,
                "grade": {"$ne": None},
            },
            {"document_index": 1, "grade": 1},
        )
        if q["document_index"] not in deleted
    }
    if not grades:
        return {"pages": 0, "staged": 0}

    max_points = _points(job, question_index)
    bonus = _is_bonus(job, question_index)
    candidates, opened, modal = _learn_question(
        db, storage, job_id, question_index, max_points, open_pdf, set(grades)
    )
    counts = {"pages": 0, "staged": 0}
    try:
        for index in sorted(candidates):
            with digit_bank.recording(
                job_id,
                index,
                digit_bank.INK_GRADE,
                storage=bank_storage or storage,
                question_index=question_index,
            ) as recording:
                reading = ink_grades.pick(
                    candidates[index], modal, max_points, classifier, bonus
                )
                if recording is not None:
                    page_size = (
                        candidates[index][0].page_size
                        if candidates[index]
                        else (612.0, 792.0)
                    )
                    if not _bankable(reading, grades[index], modal, page_size):
                        recording.kept.clear()
                    # counted before the recording closes: closing writes the
                    # kept readings out and empties the list
                    counts["staged"] += bool(recording.kept)
            counts["pages"] += 1
    finally:
        for doc in opened:
            try:
                doc.close()
            except Exception:
                pass
    return counts


def _bankable(
    reading: Any, grade: float, modal: Any, page_size: Tuple[float, float]
) -> bool:
    """Whether a re-read is the grade's own ink, fit to label with ``grade``.

    A reading that agrees with the grade is. One that does not is either the
    model misreading the grade -- what retraining is for -- or another mark
    altogether: a "2/2" from the breakdown, on a page where the teacher typed
    a 7 because no total was written. Only the first kind is kept: a reading
    the reader trusted, of the mark at a learned grade position.
    """
    if reading.grade is None:
        return False
    if abs(reading.grade - grade) <= 1e-6:
        return True
    if not reading.confident or not modal or reading.bbox is None:
        return False
    positions = modal if isinstance(modal[0], (list, tuple)) else [modal]
    x0, y0, x1, y1 = reading.bbox
    cx = (x0 + x1) / 2 / page_size[0]
    cy = (y0 + y1) / 2 / page_size[1]
    return any(
        ((cx - mx) ** 2 + (cy - my) ** 2) ** 0.5 <= ink_grades.POSITION_RADIUS
        for mx, my in positions
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

    pending_indices = {document["document_index"] for document in pending}
    candidates, opened, modal = _learn_question(
        db, storage, job_id, question_index, max_points, open_pdf, pending_indices
    )

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
            with digit_bank.recording(
                job_id, index, digit_bank.INK_GRADE, question_index=question_index
            ):
                reading = ink_grades.pick(
                    candidates[index],
                    modal,
                    max_points,
                    classifier,
                    bonus,
                    # validated in the app with no grade: the teacher says a
                    # grade is written on this page
                    lone_mark_trusted=bool(claimed.get("submitted")),
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
