"""Writing the grades of a validated job on the cover pages of its copies.

The graded page is written beside the scan, under ``graded/``, and the scan
itself is never touched: finalizing used to overwrite the cover page and keep
the original as ``_cover_nograde.pdf``, so what the validation screen showed
depended on whether the job had been finalized, and a second finalization
read back what the first one had written. The merge picks the graded page up
when it exists (see utils.merge).

Because the page is a file of its own, a run that is interrupted does not
have to start over: every graded page carries, in its copy's record, what it
was drawn from, and a copy whose page is already the page this code would
write is left alone.
"""

import os

from process_copy.batching import max_ram_gb, run_batch
from process_copy.config import grade_box as def_grade_box
from process_copy.database import Database
from process_copy.imaging import memory_used_gb
from process_copy.recognize import add_grades
from rmn_common.questions import ignored_positions
from rmn_common.status import Document_Status
from rmn_common.storage import GRADED_COVER_DIR
from utils.storage import Storage

storage = Storage()


# A cover page costs about 100 MB of page images and the imaging libraries do
# not give all of it back (see process_copy.batching). A batch that dies
# anyway costs its copy, not the finalisation; past this many deaths
# something else is wrong and finalising is pointless.
MAX_WORKER_DEATHS = 10


# What a graded page was drawn from is recorded with the copy, so a
# finalization that starts again (its executor was killed, its owner changed
# two grades) only redraws the pages that would come out different. Bump this
# whenever what is drawn changes -- the grades alone do not say whether the
# page on disk is the page this code would write now.
COVER_WRITER_VERSION = 4


def grades_to_write(grades, n_questions, ignored):
    """
    Build the list of texts to write in the grade boxes of a cover page.

    Args:
        grades (list): The grades stored for the copy, one per question.
        n_questions (int): The number of questions of the template (its number
            of grade boxes minus the total box).
        ignored (set): 0-based positions of the ignored questions.

    Returns:
        list: One text per grade box, the total last. An ignored question or a
              missing grade gives an empty text so its box is left blank.
    """
    grades = list(grades)[:n_questions] + [None] * (n_questions - len(grades))
    texts = ["" if i in ignored or g is None else str(g) for i, g in enumerate(grades)]
    total = sum(g for i, g in enumerate(grades) if i not in ignored and g is not None)
    texts.append(str(total))
    return texts


def cover_signature(texts, box_grades):
    """
    What a graded cover page was drawn from.

    Args:
        texts (list): The grades written in the boxes (see grades_to_write).
        box_grades (tuple): The grade box of the template it was written in.

    Returns:
        dict: Recorded with the copy; a page whose signature still matches is
              not drawn again.
    """
    return {
        "version": COVER_WRITER_VERSION,
        "box": [round(float(side), 6) for side in box_grades],
        "texts": list(texts),
    }


def scan_path(rel_filepath):
    """
    The cover page as it was scanned, whatever an older run did to it.

    Args:
        rel_filepath (str): The cover page of the copy, as recorded.

    Returns:
        str: The absolute path to read the page from: the ``_nograde`` backup
             when a finalization that still overwrote the scan left one, the
             recorded page otherwise.
    """
    path = storage.abs_path(rel_filepath)
    backup = path.replace(".pdf", "_nograde.pdf")
    return backup if os.path.exists(backup) else path


def graded_path(rel_filepath):
    """
    Where the graded version of a cover page goes.

    Args:
        rel_filepath (str): The cover page of the copy, as recorded.

    Returns:
        str: The absolute path of the graded page, under ``graded/``.
    """
    path = storage.abs_path(rel_filepath)
    return os.path.join(os.path.dirname(path), GRADED_COVER_DIR, os.path.basename(path))


def write_cover_page(doc, grades, box_grades, shape, cells=None):
    """
    Write the grades of one copy on a copy of its cover page.

    Args:
        doc (dict): The copy, as stored in job_documents.
        grades (list): One text per grade box (see grades_to_write).
        box_grades (tuple): The grade table of the template, in page fractions.
        shape (tuple): The size the raster of the page should have, in pixels.
        cells (list): The grade boxes found on the template, in page
            fractions; None for a template processed before they were kept.

    Returns:
        bool: True when the graded page was written, False when the table was
              not found -- the scan is then the only page there is, and the
              merge falls back to it.
    """
    source = scan_path(doc["rel_filepath"])
    target = graded_path(doc["rel_filepath"])
    os.makedirs(os.path.dirname(target), exist_ok=True)

    written = False
    try:
        written = add_grades(grades, source, box_grades, target, add_border=False, shape=shape,
                             cells=cells)
    except Exception as e:
        print(f"Error while adding grades to {source}: {e}")
    if not written and os.path.exists(target):
        # an earlier run may have written one: it belongs to grades that are
        # no longer the grades of this copy
        os.remove(target)
    return written


def write_batch(documents, start, n_docs, settings, events):
    """
    Write the cover pages of ``documents``, until the memory guard stops it.

    Runs in a process of its own (see process_copy.batching). Every copy it
    finishes is reported on ``events`` as it goes, so a parent whose batch is
    killed knows where to resume, and the last event says where the next
    batch starts.

    Args:
        documents (list): The copies to write, from ``start`` on.
        start (int): Position of the first copy in the job.
        n_docs (int): Number of copies of the job, for the progress lines.
        settings (dict): box_grades, shape, n_questions, ignored and
            max_RAM_GB.
        events (queue): ("done"|"kept"|"failed", position) per copy -- written,
            left as it was, or no overlay -- then ("next", position) when the
            batch stops.
    """
    position = start - 1
    for position, doc in enumerate(documents, start=start):
        if doc["status"] == Document_Status.DELETED.value:
            # a deleted copy is never graded (grades are [None, ...]); skip it
            # instead of falling through and summing None (which crashed finalize)
            print(f"({position + 1}/{n_docs}) PDF is deleted {doc['rel_filepath']}")
            events.put(("kept", position))
            continue

        # an ignored question keeps its (blank) box so the other grades stay aligned
        grades = grades_to_write(doc["grades"], settings["n_questions"], settings["ignored"])
        if (doc.get("graded_cover") == cover_signature(grades, settings["box_grades"])
                and os.path.exists(graded_path(doc["rel_filepath"]))):
            # same grades, same box, same way of drawing them: the page of the
            # run that was interrupted is the page this one would write
            print(f"({position + 1}/{n_docs}) Graded cover page already written for "
                  f"{doc['rel_filepath']}")
            events.put(("kept", position))
            continue

        written = write_cover_page(doc, grades, settings["box_grades"], settings["shape"],
                                   settings.get("grade_cells"))
        if written:
            print(f"({position + 1}/{n_docs}) Graded cover page saved as "
                  f"{graded_path(doc['rel_filepath'])}")
        else:
            print(f"({position + 1}/{n_docs}) Grades NOT written for "
                  f"{doc['rel_filepath']}: the scanned cover page is used as it is")
        events.put(("done" if written else "failed", position))

        used = memory_used_gb()
        if used >= settings["max_RAM_GB"]:
            print(f"Memory guard: {used:.1f} GB used, the next copies go to a new batch")
            break
    events.put(("next", position + 1))


def process_writing(job, TMP_DIR, dpi=300, shape=(8.5, 11), batches=None):
    """
    Write the graded cover page of every copy of a job.

    Args:
        job (dict): The job.
        TMP_DIR (Path): Working directory of this job.
        dpi (int): Resolution the pages are rasterised at to find their
            grade table; the pages themselves are not rasterised any more.
        shape (tuple): Page size in inches.
        batches (ProcessBatches|InlineBatches): how to run a batch; a process
            of its own by default, which is what gives the memory back.

    Returns:
        list: The document_index of the copies whose graded page could not be
              written; those are merged from their scanned cover page.
    """
    job_id = job["job_id"]
    box_grades = def_grade_box["exam"]["grade"]  # default box for grades recognition
    shape = (int(dpi * shape[0]), int(dpi * shape[1]))

    db = Database()
    front_template_id = job["front_template_id"]
    regular_template_id = job["regular_template_id"]
    box_grades_list, _, _ = db.get_templates_info(front_template_id, regular_template_id)
    if box_grades_list is not None:
        box_grades = box_grades_list
    grade_cells = db.get_template_grade_cells(front_template_id)
    n_pages_per_question = job.get("n_pages_per_question")
    if n_pages_per_question is None:
        n_pages_per_question = db.eval_jobs_collection().find_one({"job_id": job_id})["n_pages_per_question"]

    # the batches are separate processes with no database of their own:
    # everything they need is read now and sent to them, and what they wrote
    # is recorded here when they come back
    documents = list(db.documents_collection().find({"job_id": job_id}).sort("document_index", 1))

    settings = {
        "box_grades": box_grades,
        "grade_cells": grade_cells,
        "shape": shape,
        "n_questions": len(n_pages_per_question),
        "ignored": ignored_positions(n_pages_per_question),
        "max_RAM_GB": max_ram_gb(),
    }

    print("Adding grades to copies ...")
    failed = []
    try:
        _write_all(db, job_id, documents, settings, failed, batches)
    finally:
        db.close()
    if failed:
        print(f"Grades could not be written on {len(failed)} cover page(s): documents {failed}")
    return failed


def _record_cover(db, job_id, doc, signature):
    """Record what the graded page of a copy was drawn from, or that it has none.

    Args:
        db (Database): The database.
        job_id (str): The job.
        doc (dict): The copy.
        signature (dict): See cover_signature; None when the copy has no
            graded page any more.
    """
    change = ({"$set": {"graded_cover": signature}} if signature
              else {"$unset": {"graded_cover": ""}})
    db.documents_collection().update_one(
        {"job_id": job_id, "document_index": doc["document_index"]}, change)


def _write_all(db, job_id, documents, settings, failed, batches):
    """Write the copies batch after batch, and record what each one wrote.

    Args:
        db (Database): Where the signature of a written page is recorded.
        job_id (str): The job.
        documents (list): Its copies, by document_index.
        settings (dict): What a batch needs, see process_writing.
        failed (list): Filled with the document_index of the copies whose
            graded page could not be written.
        batches (ProcessBatches|InlineBatches): how to run a batch.
    """
    n_docs = len(documents)
    deaths = 0
    position = 0
    while position < n_docs:
        received, exitcode = run_batch(
            write_batch, (documents[position:], position, n_docs, settings), batches)

        resume = None
        last_done = position - 1
        for kind, value in received:
            if kind == "next":
                resume = value
                continue
            last_done = value
            doc = documents[value]
            if kind == "done":
                # what the page was drawn from, so a run that starts again
                # leaves it alone
                texts = grades_to_write(doc["grades"], settings["n_questions"], settings["ignored"])
                _record_cover(db, job_id, doc, cover_signature(texts, settings["box_grades"]))
            elif kind == "failed":
                failed.append(doc["document_index"])
                # there is no graded page any more: the next run must try again
                _record_cover(db, job_id, doc, None)

        if resume is None:
            # killed (the container ran out of memory, a page the imaging
            # libraries choked on): resume after what it wrote and skip the
            # copy it died on, instead of restarting on it for ever
            deaths += 1
            dead_at = last_done + 1
            print(f"The batch writing the cover pages died (exit code {exitcode}) "
                  f"at copy {dead_at + 1}/{n_docs}")
            if deaths >= MAX_WORKER_DEATHS:
                raise RuntimeError(f"{deaths} batches died while writing the cover pages of {job_id}")
            if dead_at < n_docs:
                failed.append(documents[dead_at]["document_index"])
                _record_cover(db, job_id, documents[dead_at], None)
            resume = dead_at + 1
        position = resume
