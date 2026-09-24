"""Removing a job: while it is being processed, and on request."""

import glob
import os
from runtime import timestamped_print



# the executor timestamps every line it prints (see runtime.timestamped_print)
print = timestamped_print




def cleanup_deleted_job(db, storage, job_id):
    # The job was deleted (via /job/delete) while it was being processed:
    # the server already removed everything it knew about, so mirror that
    # deletion here for the data recreated since then.
    print("Job has been deleted. Cleaning up recreated data...")
    storage.clean_storage(job_id)
    for folder in ("zips", "corrected_copies"):
        try:
            storage.remove_tree(os.path.join(folder, job_id))
        except Exception:
            pass
    for file_id in (os.path.normpath(f"output_csv{os.sep}{job_id}.csv"),
                    os.path.normpath(f"output_stats{os.sep}{job_id}.pdf")):
        try:
            storage.remove(file_id)
        except Exception:
            pass
    for zip_path in glob.glob(storage.abs_path(os.path.normpath(f"output_zip{os.sep}{job_id}_*.zip"))):
        try:
            os.remove(zip_path)
        except Exception:
            pass
    try:
        db.documents_collection().delete_many({"job_id": job_id})
        db.questions_collection().delete_many({"job_id": job_id})
        db.jobs_output_collection().delete_many({"job_id": job_id})
        db.mongo_database["versions"].delete_many({"job_id": job_id})
    except Exception as e:
        print(e)



def delete_job(db, storage, job_id):
    """Drain a delete task: remove the job's storage and database records.

    The server already removed the eval_jobs record synchronously and
    enqueued this task, so the heavy (NFS) cleanup runs here off the web
    request path.
    """
    print("Delete job:", job_id)
    try:
        storage.remove_job(job_id)
    except Exception as e:
        print(e)
    for collection in ("job_documents", "job_questions", "eval_jobs", "jobs_output", "versions"):
        try:
            db.get_collection(collection).delete_many({"job_id": job_id})
        except Exception as e:
            print(e)
