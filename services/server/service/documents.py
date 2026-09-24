"""Putting graded copies back: where their files go, and what is read from them."""

import json
import os
import re
import shutil
from zipfile import ZipFile
from rmn_common import auto_grade
from rmn_common.status import Document_Status
from auth import question_allowed
from context import TEMP_FOLDER, mongo, redis, storage
from service.versions import get_last_version, save_new_pdf_version


def skipped_questions(validity, job_id, zip_path, grades):
    """The questions of an upload this caller may not modify.

    The pdfs and the csv rows of a question outside the caller's scope are
    dropped, one by one, deep inside a thread whose answer has already been
    sent -- so the upload looked like it had worked in full. This is read
    before the thread starts, so the answer can name what will not be
    written.

    Args:
        validity: The share-token scope, None for the job owner.
        job_id: The job the upload belongs to.
        zip_path: The uploaded archive; a broken one names no question here
            and fails in the thread as it did before.
        grades: The csv grades, keyed by document index.

    Returns:
        The refused questions, as the labels the teacher sees ("Q2"), sorted.
    """
    questions = set()
    try:
        with ZipFile(zip_path, "r") as zip_file:
            for name in zip_file.namelist():
                found = re.search(r"Q(\d+)(?=\.pdf$)", name)
                if found:
                    questions.add(int(found.group(1)))
    except Exception as e:
        print(f"{job_id}: cannot list the uploaded zip ({e})")
    if grades:
        # the csv covers copies, which carry their own question
        questions.update(mongo["RMN"]["job_questions"].distinct(
            "question_index",
            {"job_id": job_id,
             "document_index": {"$in": [int(i) for i in grades]}},
        ))
    # a copy with no question (a whole-copy upload) has nothing to name
    refused = [
        q for q in questions
        if q is not None and not question_allowed(validity, q)
    ]
    return [f"Q{q}" for q in sorted(refused)]


def replace_thread(validity, job_id, grades, temp_file, read_grades=False):
    # the temp file is removed whatever happens: an exception in the detached
    # thread used to leak it (the 200 has already been sent)
    try:
        replace_documents(validity, job_id, grades, temp_file.name, read_grades)
    finally:
        temp_file.close()
        if os.path.exists(temp_file.name):
            os.remove(temp_file.name)


def replace_documents(validity, job_id, grades, zip_path, read_grades=False):
    # read_grades has to be a parameter: without one the name resolved to the
    # /job/read_grades view function, which is always truthy, so the flag was
    # never actually read and no test could tell
    db = mongo["RMN"]

    for doc_index, grade in grades.items():
        doc_index = int(doc_index)
        q_doc = db["job_questions"].find_one({"job_id": job_id, "document_index": doc_index})
        if q_doc is None:
            print('Invalid document_index:', job_id, doc_index)
            continue

        # scope before the write: the status and grade used to be updated
        # first and only the job_documents mirror skipped
        if not question_allowed(validity, q_doc["question_index"]):
            print("You don't have access to question", q_doc["question_index"])
            continue

        db["job_questions"].update_one(
            {"job_id": job_id, "document_index": doc_index},
            {"$set": {
                "status": Document_Status.VALIDATED.value,
                "grade": grade
            }}
        )

        q_index = int(q_doc["question_index"]) - 1
        r = db["job_documents"].update_one(
            {"job_id": job_id, "filename": q_doc["basename"]},
            {"$set": {
                f"grades.{q_index}": grade
            }}
        )
        if not r:
            print('Invalid filename:', job_id, q_doc["basename"])

    touched_questions = set()
    with ZipFile(zip_path, 'r') as zip_file:
        for file_info in zip_file.infolist():
            if not file_info.filename.endswith(".pdf"):
                continue

            extracted_path = zip_file.extract(file_info, path=TEMP_FOLDER)
            # extracting question number from the filename
            question_number = re.search(r'Q\d+(?=\.pdf$)', file_info.filename)
            if question_number:
                question_folder = question_number.group(0)
                # validity = None => logged user
                if not question_allowed(validity, question_folder[1:]):
                    print("You don't have access to question", question_folder)
                    continue

                storage_path = os.path.join('documents', job_id, question_folder, os.path.basename(file_info.filename))
                final_destination = storage.abs_path(storage_path)

                if not os.path.exists(os.path.dirname(final_destination)):
                    os.makedirs(os.path.dirname(final_destination), exist_ok=True)

                # moving the extracted file to the final destination
                shutil.move(extracted_path, final_destination)
                # save new version
                version_filepath = save_new_pdf_version(final_destination)
                last_version = get_last_version(job_id, storage_path)
                db["versions"].insert_one(
                    {"job_id": job_id, "rel_filepath": storage_path, "version": last_version + 1,
                     "version_filepath": version_filepath, "annotations": []}
                )
                touched_questions.add(int(question_folder[1:]))

    if read_grades and touched_questions:
        start_reading_grades(job_id, sorted(touched_questions))
    elif read_grades:
        print(f"{job_id}: nothing to read, the upload carried no question pdf")


def start_reading_grades(job_id, question_indices):
    """Queue a reading pass per question whose pages were just replaced.

    One payload per question, because that is the unit of work: two questions
    uploaded separately are read at the same time by the two executor pods.
    The run number is what lets a second upload of the same question overtake
    the first -- the executor re-checks it and abandons a pass that is no
    longer current.

    This runs after the files are in the storage tree: an executor pod picking
    the job up earlier would read whatever was there before.
    """
    db = mongo["RMN"]
    for question_index in question_indices:
        try:
            run = auto_grade.start_run(
                db["eval_jobs"], db["job_questions"], job_id, question_index
            )
            redis.rpush("job_queue", json.dumps({
                "job_id": job_id,
                "read_grades": True,
                "question_index": question_index,
                "run": run,
            }))
        except Exception as e:
            print(f"Could not queue the grade reading of Q{question_index}: {e}")
