"""Splitting the copies of a new job, and reading the matricule of each."""

import datetime as dt
import os
from python.process_copy.parser import parse_run_args
from rmn_common.spreadsheet import defuse_csv
from rmn_common.status import Document_Status, Job_Status
from runtime import MAX_RETRY, apply_template_boxes, timestamped_print
from tasks.cleanup import cleanup_deleted_job
from tasks.copies import add_copies_to_job
from utils.clients import update_status



# the executor timestamps every line it prints (see runtime.timestamped_print)
print = timestamped_print




    # delete preview image
    # print("Clean documents and unverified_numbers")
    # docs = db.documents_collection().find({"job_id": job_id})
    # for doc in docs:
    #     # delete unverified numbers for job
    #     document_index = doc["document_index"] - 1
    #     for image_index in range(len(doc["grades"].keys())):
    #         try:
    #             storage.remove(os.path.normpath(
    #                 f"unverified_numbers{os.sep}{job_id}{os.sep}{document_index}{os.sep}{image_index}.png"))
    #         except:
    #             continue

    # try:
    #     storage.remove_tree(os.path.normpath(f"documents{os.sep}{job_id}"))
    #     storage.remove_tree(os.path.normpath(f"corrected_copies{os.sep}{job_id}"))
    # except:
    #     pass

    # db.questions_collection().delete_many({"job_id": job_id})
    # db.documents_collection().delete_many({"job_id": job_id})

def process_job(db, storage, sio, job, TMP_DIR, stopH):
    job_id = job["job_id"]
    user_id = job["user_id"]

    # make directories
    MOODLE_FOLDER = TMP_DIR.joinpath("moodle")
    OUTPUT_FOLDER = TMP_DIR.joinpath("output")
    MOODLE_FOLDER.mkdir(exist_ok=True)
    OUTPUT_FOLDER.mkdir(exist_ok=True)

    # Query job params
    print("Querying job details from Database...")
    job_params = db.eval_jobs_collection().find_one({"job_id": job_id})

    if job_params is None:
        print("No params found!")
        return

    print(job_params)
    db.eval_jobs_collection().update_one(
        {"job_id": job_id},
        {
            "$set": {
                "job_status": Job_Status.RUN.value,
                "alive_time": dt.datetime.now(dt.UTC)
            }
        }
    )

    # Save notes.csv file to local
    storage.copy_from(job_params["notes_file_id"], str(OUTPUT_FOLDER.joinpath("notes.csv")))

    # Path to all copies
    copies_folder = storage.abs_path(os.path.join("documents", job_id, "all"))

    # fetch the user-defined boxes
    box_grade_list, box_matricule_list, regular_box_matricule_list = \
        db.get_templates_info(job_params["front_template_id"],
                              job_params["regular_template_id"])
    apply_template_boxes(box_grade_list, box_matricule_list, regular_box_matricule_list)

    args = [
        copies_folder,
        "-m",
        str(MOODLE_FOLDER),
        "-f",
        "exam",
        "--grades",
        str(OUTPUT_FOLDER.joinpath("notes.csv")),
        "--job_id",
        job_id,
        "--user_id",
        user_id,
    ]
    print("Running module with:", args)
    # process_copy
    try:
        parse_run_args(args)
    except Exception as e:
        print("Error in process-copy:", e)

        if stopH.stop():
            cleanup_deleted_job(db, storage, job_id)
            return

        # check if should retry
        retry = job_params.get("retry", 0)
        db.eval_jobs_collection().update_one(
            {"job_id": job_id},
            {"$set": {"job_infos": str(e)}})
        if retry < MAX_RETRY:
            raise e

        # Error handling
        update_status(db, sio, user_id, job_id, Job_Status.ERROR, infos={"job_infos": str(e)})
        return

    print("Module Done")

    if stopH.stop():
        cleanup_deleted_job(db, storage, job_id)
        return

    # Save csv files in storage (downloadable from here on: formulas out)
    notes_csv_file_id = os.path.normpath(f"output_csv{os.sep}{job_id}.csv")
    defuse_csv(os.path.join(OUTPUT_FOLDER, "notes.csv"))
    storage.move_to(os.path.join(OUTPUT_FOLDER, "notes.csv"), notes_csv_file_id)

    # finalize job: add job output to database if not existinf already -> first time the job is processed
    db.jobs_output_collection().update_one(
        {"job_id": job_id},  # filter for existing document
        {"$setOnInsert": {
            "job_id": job_id,
            "user_id": user_id,
            "notes_csv_file_id": notes_csv_file_id,
            "preview_file_id": "None",
            "zip_id_list": [],
        }},  # set fields if document does not exist
        upsert=True
    )

    # Set Job status to VALIDATION if all document are processed
    n_not_neady_docs = db.documents_collection().count_documents({
        "job_id": job_id,
        "status": Document_Status.NOT_READY.value
    })
    if n_not_neady_docs == 0:
        # Set Job status to VALIDATED if all documents are processed
        update_status(db, sio, user_id, job_id, Job_Status.VALIDATION,
                      infos={"job_infos": "Validation matricule prête"})



def create_job(db, redis, storage, sio, job, TMP_DIR):
    job_id = job["job_id"]
    user_id = job["user_id"]

    try:
        add_copies_to_job(db, redis, storage, sio, job, TMP_DIR, Job_Status.RETRY)

    except Exception as e:
        print(e)
        # Set Job status to ERROR
        update_status(db, sio, user_id, job_id, Job_Status.ERROR, infos={"job_infos": str(e)})
