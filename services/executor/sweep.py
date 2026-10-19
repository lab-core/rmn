"""Requeue the jobs whose executor died.

The sweep used to run at the end of every executor pod, and nowhere else.
KEDA only starts a pod when the Redis queue is not empty, so a job whose
executor was killed mid-run was requeued only if somebody else happened to
submit a job: ``d98c2837`` sat in FINALIZING for eleven hours after its pod
was OOM-killed, because the pod that replaced it swept twelve seconds later,
while the job still looked alive. The CronJob of ``deployment/sweep.yml``
runs this module on its own schedule; the executor still sweeps when it ends.
"""

import datetime as dt
import json
import os
import sys
import time

from rmn_common.status import Job_Status
from runtime import MAX_IDLE_TIME, MAX_RETRY, timestamped_print
from utils.clients import update_status


# the executor timestamps every line it prints (see runtime.timestamped_print)
print = timestamped_print


def check_for_idle_jobs_to_requeue(db, redis, sio, sleep):
    """Send the jobs that stopped making progress back to the queue.

    Args:
        db (Database): The database.
        redis (Redis): The job queue.
        sio (Client): The socket.io client status changes are announced on.
        sleep (bool): Wait and look again while every running job is idle.
    """
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
                        # VALIDATED, not VALIDATION: the executor finalizes a
                        # VALIDATED job and ignores a VALIDATION one, so the
                        # requeued finalization used to be dropped on the floor
                        # and the job waited for its owner to press the button
                        # again
                        requeue(Job_Status.FINALIZING.value, Job_Status.VALIDATED.value)

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
    # the CronJob: one pass, no storage share and no job of its own
    from python.process_copy.database import Database
    from utils.clients import redis_client, socketio_client

    print("Sweeping the idle jobs...")
    db = Database()
    redis = redis_client()
    sio = socketio_client()
    try:
        check_for_idle_jobs_to_requeue(db, redis, sio, sleep=False)
    except Exception as e:
        print("Sweep failed:", e)
        sys.exit(1)
    finally:
        db.close()
        sio.disconnect()
    print("Sweep done.")
    sys.exit(os.EX_OK)
