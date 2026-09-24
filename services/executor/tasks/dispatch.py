"""Which task a job from the queue is: its status decides."""

from rmn_common.status import Job_Status
from runtime import Heartbeat, timestamped_print
from tasks.copies import add_copies_to_job
from tasks.finalize import finalize_job
from tasks.process import create_job, process_job
from tasks.read_grades import read_grades_for_job
from utils.clients import update_status
from utils.stop_handler import StopHandler



# the executor timestamps every line it prints (see runtime.timestamped_print)
print = timestamped_print




def process(db, redis, storage, sio, p_job, TMP_DIR):
    job_id = p_job["job_id"]
    job = db.eval_jobs_collection().find_one({"job_id": job_id})
    if not job:
        raise KeyError(f"Job {job_id} not found in mongodb.")

    stopH = StopHandler(db.eval_jobs_collection(), job_id)

    # keep alive_time fresh for the whole (possibly long) operation so the
    # idle checker does not wrongly requeue a job that is still working
    with Heartbeat(db, job_id):
        if job["job_status"] in [Job_Status.VALIDATED.value, Job_Status.FINALIZING.value]:
            try:
                finalize_job(db, storage, sio, job, TMP_DIR, stopH)
            except Exception as e:
                # left in FINALIZING, the job was sent back to VALIDATION
                # by the idle sweep with no message, on every attempt
                print("Error while finalizing job", job_id, ":", e)
                update_status(db, sio, job["user_id"], job_id, Job_Status.ERROR,
                              infos={"job_infos": f"Échec de la finalisation : {e}"})

        elif p_job.get("read_grades") and job["job_status"] in [
                Job_Status.QUEUED.value, Job_Status.RUN.value,
                Job_Status.VALIDATION.value]:
            read_grades_for_job(db, storage, sio, job, p_job.get("question_index"),
                                p_job.get("run"), stopH)

        elif (p_job.get("add_copies") and
              job["job_status"] in [Job_Status.QUEUED.value, Job_Status.RUN.value, Job_Status.VALIDATION.value]):
            add_copies_to_job(db, redis, storage, sio, job, TMP_DIR)

        elif job["job_status"] in [Job_Status.QUEUED.value, Job_Status.IGNORED.value]:
            process_job(db, storage, sio, job, TMP_DIR, stopH)

        elif job["job_status"] in [Job_Status.SPLIT.value, Job_Status.CORRECTED.value]:
            create_job(db, redis, storage, sio, job, TMP_DIR)

        else:
            print("Job status "+job["job_status"]+" not handled.")
