"""The executor process: take a job off the queue and run what it asks for.

The tasks themselves live in ``tasks/``, one module per kind of job, and are
given the clients created here. What they share with no state of their own is
in ``runtime.py``. This file is the loop.

The tasks are imported once a job has been taken, not at start-up: importing
them is two and a half seconds of OpenCV and LiteRT, and the queue still
shows the job during that time, which is long enough for the scaler to start
a second executor for work this one has already taken.
"""

import os
import re
import shutil
import json
from pathlib import Path
from python.process_copy.database import Database
from utils.storage import Storage
from sweep import check_for_idle_jobs_to_requeue
from utils.clients import redis_client, socketio_client
from runtime import MAX_IDLE_TIME, timestamped_print


# the executor timestamps every line it prints (see runtime.timestamped_print)
print = timestamped_print


ROOT_DIR = Path(__file__).resolve().parent


# job ids come from the Redis queue and name directories: server-generated
# UUIDs, so anything else is refused before it becomes a path
JOB_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def valid_job_id(job_id):
    return isinstance(job_id, str) and JOB_ID_PATTERN.fullmatch(job_id) is not None


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
                    # the recognition stack, loaded now that the job is ours
                    # (see the module docstring)
                    from tasks.cleanup import delete_job
                    from tasks.dispatch import process
                    from tasks.templates import process_template

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
            check_for_idle_jobs_to_requeue(db, redis, sio, not blocking)

    except Exception as e:
        print(e)
    finally:
        db.close()
        sio.disconnect()
    print("Job end.")
