"""Writing the grades of a validated job on the cover pages of its copies.

The graded page is written beside the scan, under ``graded/``, and the scan
itself is never touched: finalizing used to overwrite the cover page and keep
the original as ``_cover_nograde.pdf``, so what the validation screen showed
depended on whether the job had been finalized, and a second finalization
read back what the first one had written. The merge picks the graded page up
when it exists (see utils.merge).
"""

import os

import img2pdf
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


def write_cover_page(doc, grades, img_path, box_grades, dpi, shape):
    """
    Write the grades of one copy on a copy of its cover page.

    Args:
        doc (dict): The copy, as stored in job_documents.
        grades (list): One text per grade box (see grades_to_write).
        img_path (str): Scratch image the overlay is drawn into.
        box_grades (tuple): The grade table of the template, in page fractions.
        dpi (int): Resolution of the page written.
        shape (tuple): Page size in pixels.

    Returns:
        bool: True when the graded page was written, False when the overlay
              failed -- the scan is then the only page there is, and the merge
              falls back to it.
    """
    source = scan_path(doc["rel_filepath"])
    target = graded_path(doc["rel_filepath"])

    # one scratch image serves every copy: remove it first, so a failed
    # overlay cannot leave the previous student's cover page in place and
    # have it written into this copy's pdf below
    if os.path.exists(img_path):
        os.remove(img_path)
    try:
        add_grades(grades, source, box_grades, img_path, add_border=False, shape=shape)
    except Exception as e:
        print(f"Error while adding grades to {source}: {e}")
    if not os.path.exists(img_path):
        # an earlier run may have written one: it belongs to grades that are
        # no longer the grades of this copy
        if os.path.exists(target):
            os.remove(target)
        return False

    os.makedirs(os.path.dirname(target), exist_ok=True)
    layout = img2pdf.get_fixed_dpi_layout_fun((dpi, dpi))
    with open(target, "wb") as f:
        f.write(img2pdf.convert(img_path, layout_fun=layout))
    return True


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
        settings (dict): img_path, box_grades, dpi, shape, n_questions,
            ignored and max_RAM_GB.
        events (queue): ("done"|"failed", position) per copy, then
            ("next", position) when the batch stops.
    """
    position = start - 1
    for position, doc in enumerate(documents, start=start):
        if doc["status"] == Document_Status.DELETED.value:
            # a deleted copy is never graded (grades are [None, ...]); skip it
            # instead of falling through and summing None (which crashed finalize)
            print(f"({position + 1}/{n_docs}) PDF is deleted {doc['rel_filepath']}")
            events.put(("done", position))
            continue

        # an ignored question keeps its (blank) box so the other grades stay aligned
        grades = grades_to_write(doc["grades"], settings["n_questions"], settings["ignored"])
        written = write_cover_page(doc, grades, settings["img_path"], settings["box_grades"],
                                   settings["dpi"], settings["shape"])
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
        dpi (int): Resolution of the pages written.
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
    n_pages_per_question = job.get("n_pages_per_question")
    if n_pages_per_question is None:
        n_pages_per_question = db.eval_jobs_collection().find_one({"job_id": job_id})["n_pages_per_question"]

    # the batches are separate processes with no database of their own:
    # everything they need is read now and sent to them
    documents = list(db.documents_collection().find({"job_id": job_id}).sort("document_index", 1))
    db.close()

    settings = {
        "img_path": str(TMP_DIR.joinpath('intermediate_image.jpg')),
        "box_grades": box_grades,
        "dpi": dpi,
        "shape": shape,
        "n_questions": len(n_pages_per_question),
        "ignored": ignored_positions(n_pages_per_question),
        "max_RAM_GB": max_ram_gb(),
    }

    n_docs = len(documents)
    print("Adding grades to copies ...")
    failed = []
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
            if kind == "failed":
                failed.append(documents[value]["document_index"])

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
            resume = dead_at + 1
        position = resume

    if failed:
        print(f"Grades could not be written on {len(failed)} cover page(s): documents {failed}")
    return failed
