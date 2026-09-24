"""Deleting a job, and the jobs nobody came back for."""

import datetime as dt
import json
from context import mongo, redis, storage


def delete_job(job_id):
    """Remove all storage and database records for a job (synchronous).

    /job/delete offloads this to an executor via the queue; delete_old_jobs
    (admin sweep) and the enqueue fallback call it directly.
    """
    print("Delete job:", job_id)

    # remove any queued reference to the job so the executor never picks it up
    # (payloads must match the exact strings pushed to the queue)
    try:
        redis.lrem("job_queue", 0, json.dumps({"job_id": job_id}))
        redis.lrem("job_queue", 0, json.dumps({"job_id": job_id, "add_copies": True}))
    except Exception as e:
        print(e)

    try:
        # targeted per-job deletion; remove_all_match walked the whole storage
        # tree on every call and made concurrent deletes hang the worker
        storage.remove_job(job_id)
    except Exception as e:
        print(e)

    db = mongo["RMN"]
    for collection in ("job_documents", "job_questions", "eval_jobs", "jobs_output", "versions"):
        try:
            db[collection].delete_many({"job_id": job_id})
        except Exception as e:
            print(e)


def delete_old_jobs(n_days_old=0, user_id=None):
    db = mongo["RMN"]
    collection = db["eval_jobs"]
    r = {} if user_id is None else {"user_id": user_id}
    jobs = collection.find(r)

    now = dt.datetime.now(dt.UTC)
    n = 0
    for j in jobs:
        delta = now - j["queued_time"].replace(tzinfo=dt.UTC)
        if delta.days >= n_days_old:
            delete_job(j["job_id"])
            n = n + 1

    return n
