"""Writing the grades of a validated job on the cover pages of its copies."""

import multiprocessing
import os
import shutil

import img2pdf
from process_copy.config import grade_box as def_grade_box
from process_copy.database import Database
from process_copy.imaging import memory_used_gb
from process_copy.recognize import add_grades
from rmn_common.questions import ignored_positions
from rmn_common.status import Document_Status
from utils.storage import Storage

storage = Storage()


# A cover page costs about 100 MB of page images and the imaging libraries do
# not give all of it back, so one process writing hundreds of copies grows out
# of the container: job d98c2837 (546 copies) was OOM-killed at copy 314 and
# its finalisation never resumed. The copies are written in batches, each in a
# process of its own, and a batch ends as soon as it has used MAX_RAM_GB: what
# it did not release goes back to the system when it exits.
#
# A batch that dies anyway (a page the imaging libraries choke on) costs its
# copy, not the finalisation; past this many deaths something else is wrong and
# finalising is pointless.
MAX_WORKER_DEATHS = 10


# spawn, never fork: the heartbeat that keeps the job from looking idle runs
# in a thread of this process while finalization goes on, and a fork only
# copies the thread that called it -- a child that inherits a lock the
# heartbeat held deadlocks on its first allocation (on macOS it segfaults as
# soon as the imaging libraries are loaded). A batch pays an import to start,
# a second or two every few hundred copies.
MP_CONTEXT = multiprocessing.get_context("spawn")


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


def write_cover_page(doc, grades, img_path, box_grades, dpi, shape):
    """
    Write the grades of one copy on its cover page.

    Args:
        doc (dict): The copy, as stored in job_documents.
        grades (list): One text per grade box (see grades_to_write).
        img_path (str): Scratch image the overlay is drawn into.
        box_grades (tuple): The grade table of the template, in page fractions.
        dpi (int): Resolution of the page written back.
        shape (tuple): Page size in pixels.

    Returns:
        bool: True when the pdf was rewritten, False when the overlay failed
              and the original cover page was kept.
    """
    input_pdf_path = storage.abs_path(doc["rel_filepath"])

    # copy a backup of the original cover page
    input_pdf_path_backup = input_pdf_path.replace(".pdf", "_nograde.pdf")
    if not os.path.exists(input_pdf_path_backup):
        shutil.copy(input_pdf_path, input_pdf_path_backup)

    # one scratch image serves every copy: remove it first, so a failed
    # overlay cannot leave the previous student's cover page in place and
    # have it written into this copy's pdf below
    if os.path.exists(img_path):
        os.remove(img_path)
    try:
        # use backup to add grades (not to overwrite grades if re-processing)
        add_grades(grades, input_pdf_path_backup, box_grades, img_path, add_border=False, shape=shape)
    except Exception as e:
        print(f"Error while adding grades to {input_pdf_path}: {e}")
    if not os.path.exists(img_path):
        return False

    layout = img2pdf.get_fixed_dpi_layout_fun((dpi, dpi))
    with open(input_pdf_path, "wb") as f:
        f.write(img2pdf.convert(img_path, layout_fun=layout))
    return True


def write_batch(documents, start, n_docs, settings, events):
    """
    Write the cover pages of ``documents``, until the memory guard stops it.

    Runs in a process of its own (see MAX_WORKER_DEATHS). Every copy it
    finishes is reported on ``events`` as it goes, so a parent whose batch is
    killed knows where to resume, and the last event says where the next batch
    starts.

    Args:
        documents (list): The copies to write, from ``start`` on.
        start (int): Position of the first copy in the job.
        n_docs (int): Number of copies of the job, for the progress lines.
        settings (dict): img_path, box_grades, dpi, shape, n_questions,
            ignored and max_RAM_GB.
        events (SimpleQueue): ("done"|"failed", position) per copy, then
            ("next", position) when the batch stops.
    """
    position = start - 1
    for position, doc in enumerate(documents, start=start):
        path = storage.abs_path(doc["rel_filepath"])
        if doc["status"] == Document_Status.DELETED.value:
            # a deleted copy is never graded (grades are [None, ...]); skip it
            # instead of falling through and summing None (which crashed finalize)
            print(f"({position + 1}/{n_docs}) PDF is deleted {path}")
            events.put(("done", position))
            continue

        # an ignored question keeps its (blank) box so the other grades stay aligned
        grades = grades_to_write(doc["grades"], settings["n_questions"], settings["ignored"])
        written = write_cover_page(doc, grades, settings["img_path"], settings["box_grades"],
                                   settings["dpi"], settings["shape"])
        if written:
            print(f"({position + 1}/{n_docs}) Modified PDF saved as {path}")
        else:
            print(f"({position + 1}/{n_docs}) Grades NOT written on {path}: original cover page kept")
        events.put(("done" if written else "failed", position))

        used = memory_used_gb()
        if used >= settings["max_RAM_GB"]:
            print(f"Memory guard: {used:.1f} GB used, the next copies go to a new batch")
            break
    events.put(("next", position + 1))


def process_writing(job, TMP_DIR, dpi=300, shape=(8.5, 11), batch_runner=None):
    """
    Write the grades on the cover page of every copy of a job.

    Args:
        job (dict): The job.
        TMP_DIR (Path): Working directory of this job.
        dpi (int): Resolution of the pages written back.
        shape (tuple): Page size in inches.
        batch_runner (callable): How a batch is run, ``Process``-like
            (target, args, start, join, exitcode). The default forks, which is
            what gives the memory back; the tests run a batch in-process.

    Returns:
        list: The document_index of the copies whose cover page could not be
              written; those keep their original cover page.
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
        # the guard measures the container, so it must stay under its memory limit
        "max_RAM_GB": int(os.getenv("MAX_RAM_GB", "1000")),
    }

    n_docs = len(documents)
    print("Adding grades to copies ...")
    failed = []
    deaths = 0
    position = 0
    while position < n_docs:
        events = MP_CONTEXT.SimpleQueue()
        batch = (batch_runner or MP_CONTEXT.Process)(
            target=write_batch,
            args=(documents[position:], position, n_docs, settings, events))
        batch.start()
        last_done = position - 1
        resume = None

        def drain():
            """Read what the batch reported; sets resume when it says it is done."""
            nonlocal last_done, resume
            while not events.empty():
                kind, value = events.get()
                if kind == "next":
                    resume = value
                    continue
                last_done = value
                if kind == "failed":
                    failed.append(documents[value]["document_index"])

        while resume is None:
            batch.join(timeout=1)
            drain()
            if resume is None and batch.exitcode is not None:
                drain()  # what it wrote just before dying
                break
        batch.join()

        if resume is None:
            # killed (the container ran out of memory, a page the imaging
            # libraries choked on): resume after what it wrote and skip the
            # copy it died on, instead of restarting on it for ever
            deaths += 1
            dead_at = last_done + 1
            print(f"The batch writing the cover pages died (exit code {batch.exitcode}) "
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
