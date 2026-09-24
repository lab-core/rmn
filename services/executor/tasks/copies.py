"""Copies added to a job that already exists."""

import json
import os
from rmn_common.status import Job_Status
from runtime import timestamped_print
from tasks.cleanup import cleanup_deleted_job
from utils.clients import update_status
from utils.split import insert_copies
from utils.stop_handler import StopHandler



# the executor timestamps every line it prints (see runtime.timestamped_print)
print = timestamped_print




def add_copies_to_job(db, redis, storage, sio, job, TMP_DIR, status_for_error=None):
    job_id = job["job_id"]
    user_id = job["user_id"]
    job_params = db.eval_jobs_collection().find_one({"job_id": job_id})
    n_pages_per_question = {key: value for key, value in job_params["n_pages_per_question"]}

    stopH = StopHandler(db.eval_jobs_collection(), job_id)
    try:
        insert_copies(os.path.join('zips', job_id), job_id, n_pages_per_question, TMP_DIR)
        print("Copies inserted in database")

        if stopH.stop():
            cleanup_deleted_job(db, storage, job_id)
            return

        # Set Job status to QUEUED as no error have been raised. Process can continue
        update_status(db, sio, user_id, job_id, Job_Status.QUEUED)

        # push the job to the queue to be continued
        redis.rpush("job_queue", json.dumps({"job_id": job_id}))
    except ValueError as e:
        if stopH.stop():
            cleanup_deleted_job(db, storage, job_id)
            return

        error_messages = str(e)
        print(e)
        # Set Job status to RETRY
        if status_for_error is None:
            update_status(db, sio, user_id, job_id, Job_Status.QUEUED,
                          infos={"job_infos": error_messages}, db_infos={"copies_errors": error_messages})
            # push the job to the queue to process the good copies at least
            redis.rpush("job_queue", json.dumps({"job_id": job_id}))
        else:
            update_status(db, sio, user_id, job_id, status_for_error,
                          infos={"job_infos": error_messages}, db_infos={"copies_errors": error_messages})
