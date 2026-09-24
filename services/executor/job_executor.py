"""The executor process: take a job off the queue and run what it asks for.

The tasks themselves live in ``tasks/``, one module per kind of job, and are
given the clients created here. What they share with no state of their own is
in ``runtime.py``. This file is the loop.
"""

import os
import re
import shutil
import json
import time
import datetime as dt
from pathlib import Path
from python.process_copy.database import Database
from rmn_common.status import Job_Status
from utils.storage import Storage
from utils.clients import redis_client, socketio_client, update_status
from runtime import MAX_IDLE_TIME, MAX_RETRY, timestamped_print
from tasks.cleanup import delete_job
from tasks.dispatch import process
from tasks.templates import process_template


# the executor timestamps every line it prints (see runtime.timestamped_print)
print = timestamped_print


ROOT_DIR = Path(__file__).resolve().parent


# job ids come from the Redis queue and name directories: server-generated
# UUIDs, so anything else is refused before it becomes a path
JOB_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def valid_job_id(job_id):
    return isinstance(job_id, str) and JOB_ID_PATTERN.fullmatch(job_id) is not None


def check_for_idle_jobs_to_requeue(db, sleep):
    alive_times = {}
    collection_check = db.get_collection("check")
    locked = False
    try:
        if collection_check.count_documents({}) == 0:
            collection_check.insert_one({'locked': True})
            locked = True
        else:
            res = collection_check.update_one({'locked': False}, {'$set': {'locked': True}})
            locked = res.matched_count > 0

        if locked:
            while True:
                print("Check idle running jobs")
                # search idle jobs
                max_alive = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=MAX_IDLE_TIME)
                jobs = db.eval_jobs_collection().find({
                    # include FINALIZING so a job whose executor crashed mid-
                    # finalization is requeued too (the requeue branch below
                    # handled it but the query never selected it)
                    "job_status": {"$in": [Job_Status.RUN.value, Job_Status.FINALIZING.value]},
                    "alive_time": {"$lt": max_alive}
                })

                job = db.eval_jobs_collection().find_one({
                    "job_status": Job_Status.IGNORED.value,
                })
                if job:
                    # Set Job status from IGNORED to VALIDATION
                    job_id = job["job_id"]
                    user_id = job["user_id"]
                    update_status(db, sio, user_id, job_id, Job_Status.VALIDATION)

                # requeue old idle jobs
                old_idle_jobs = False
                for j in jobs:
                    def requeue(c_status, n_status):
                        # MAX_RETRY was only enforced when the executor raised;
                        # a job that returned without progress came back here
                        # with retry + 1 on every sweep, forever
                        if j.get("retry", 0) >= MAX_RETRY:
                            print("Give up on job", j["job_id"], "after", MAX_RETRY, "attempts")
                            update_status(db, sio, j["user_id"], j["job_id"], Job_Status.ERROR,
                                          infos={"job_infos": f"Abandon après {MAX_RETRY} tentatives sans progrès."})
                            return
                        print("Resubmit job", j["job_id"])
                        # change status to ensure that a job is not resubmitted several times
                        res = db.eval_jobs_collection().update_one(
                            {"job_id": j["job_id"], "job_status": c_status},
                            {"$inc": {"retry": 1}, "$set": {"job_status": n_status}}
                        )
                        if res.matched_count > 0:
                            redis.lpush("job_queue", json.dumps({"job_id": j["job_id"]}))

                    if j["job_status"] == Job_Status.RUN.value:
                        requeue(Job_Status.RUN.value, Job_Status.QUEUED.value)
                    else:
                        requeue(Job_Status.FINALIZING.value, Job_Status.VALIDATION.value)

                    old_idle_jobs = True

                # continue if idle jobs
                if old_idle_jobs:
                    break

                # check if all running jobs are idle. If yes, sleep, otherwise break
                print("Check alive running jobs")

                jobs = db.eval_jobs_collection().find({
                    "job_status": Job_Status.RUN.value
                })
                all_jobs_idle = False
                for j in jobs:
                    job_id = j["job_id"]
                    alive_t = alive_times.get(job_id, dt.datetime.now(dt.UTC))
                    # check if alive_time has increased, and thus job is alived
                    j["alive_time"] = j["alive_time"].replace(tzinfo=dt.UTC)
                    if j["alive_time"] > alive_t:
                        all_jobs_idle = False
                        break
                    all_jobs_idle = True
                    alive_times[job_id] = j["alive_time"]
                # if one job alive -> stop
                if not all_jobs_idle or not sleep:
                    print("All jobs are not idle.")
                    break
                # otherwise, sleep
                print("Sleep before checking again running jobs.")
                time.sleep(5)
    finally:
        # only the pod that acquired the lock releases it: an executor whose
        # conditional update matched nothing used to unlock the real holder,
        # and two executors then requeued the same jobs concurrently
        if locked:
            collection_check.update_one({'locked': True}, {'$set': {'locked': False}})


if __name__ == "__main__":
    # Connect to Mongo
    print("Setting up MongoClient...")
    db = Database()

    # create redis connection
    redis = redis_client()

    # create storage connection (local or NFS)
    storage = Storage()

    # create socketio connection
    sio = socketio_client()

    try:
        # retrieve job
        blocking = os.getenv("REDIS_POP") == "block" or os.getenv("ENVIRONMENT") != "production"
        n_loop = 0
        while blocking or n_loop <= 1:
            n_loop += 1
            print(f"[{n_loop}] Retrieving job from redis")
            if blocking:
                job = redis.blpop("job_queue", timeout=MAX_IDLE_TIME)
                # output of blocking is a tuple (job_queue, job)
                if job:
                    job = job[1]
            else:
                job = redis.lpop("job_queue")

            # process job if any
            if job:
                print("Job:", job)
                # check if job if of form (job_queue, job)
                if type(job) is tuple:
                    job = job[1]
                job = json.loads(job)

                if job:
                    # create tmp work dir
                    jid = job["template_id"] if "template_id" in job else job.get("job_id")
                    if not valid_job_id(jid):
                        print(f"Refusing job with an invalid id: {jid!r}")
                        continue
                    WORK_TMP_DIR = ROOT_DIR.joinpath(f"tmp_{jid}")
                    WORK_TMP_DIR.mkdir(exist_ok=True)

                    # process job
                    try:
                        if "template_id" in job:
                            process_template(db, storage, sio, jid, WORK_TMP_DIR)
                        elif job.get("delete"):
                            delete_job(db, storage, job["job_id"])
                        else:
                            process(db, redis, storage, sio, job, WORK_TMP_DIR)
                    except Exception as e:
                        print("Caught an error while processing job:")
                        print(e)
                        pass

                    # clean ENLEVER
                    shutil.rmtree(WORK_TMP_DIR)

            # check if any job is idle and dangling
            check_for_idle_jobs_to_requeue(db, not blocking)

    except Exception as e:
        print(e)
    finally:
        db.close()
        sio.disconnect()
    print("Job end.")
