"""The operator commands, shared by the admin-key routes and the dashboard.

``/admin/*`` (the ``ADMIN_API_KEY``, for scripts) and ``/manage/*`` (an
Administrateur's session, for the webapp's admin page) run the same code:
each function reads the form it is given and returns the response.
"""

import math

from flask import json

from context import mongo, redis, storage
from service import storage_cleanup
from service.job_cleanup import delete_job, delete_old_jobs
from service.template_service import TemplateService
from service.user_service import UserService
from utils.forms import form_int
from utils.responses import Response


def _error(message, status=400):
    return Response(response=json.dumps({"response": f"Error: {message}"}), status=status)


def _form_user(request_form):
    """The user a command targets: ``username``, else ``user_id``, else None."""
    if "username" in request_form:
        return str(request_form["username"])
    if "user_id" in request_form:
        return str(request_form["user_id"])
    return None


def delete_jobs(request_form, user_id=None):
    """Delete the jobs at least ``n_days_old`` days old (of one user, if named)."""
    if "n_days_old" not in request_form:
        return _error("n_days_old not provided.")
    n_days_old = form_int(request_form, "n_days_old")
    # a negative age puts the cutoff in the future: every job would go
    if n_days_old < 0:
        return _error("n_days_old must be >= 0.")
    n = delete_old_jobs(n_days_old, user_id)
    return Response(response=json.dumps({"response": "OK", "n_deleted_jobs": n}), status=200)


def delete_tokens(request_form, user_id=None):
    """Delete the login tokens at least ``n_days_old`` days old (0: all)."""
    n_days_old = form_int(request_form, "n_days_old", default=0)
    if n_days_old < 0:
        return _error("n_days_old must be >= 0.")
    UserService.delete_tokens(user_id, n_days_old, mongo["RMN"])
    return Response(response=json.dumps({"response": "OK"}), status=200)


def delete_account(username):
    """Delete a user with everything they own: jobs, templates, sessions."""
    db = mongo["RMN"]
    delete_old_jobs(user_id=username)
    TemplateService.delete_templates(username, db, storage)
    UserService.delete(username, db)
    return Response(response=json.dumps({"response": "OK"}), status=200)


def storage_sweep(request_form):
    """Report, and optionally delete, storage no database row owns any more.

    Form fields: ``dry_run`` (default true -- the sweep only reports),
    ``min_age_hours`` (default 24, paths touched more recently are skipped so
    the sweep cannot race an upload) and ``include_strays`` (default false --
    also delete paths under a known prefix that match no layout rule).
    ``include_empty_jobs`` (default false) also deletes the ``eval_jobs``
    rows none of whose files exist any more, with everything else of the job.
    ``usage=true`` adds a ``usage`` block: bytes used on the share by files
    older than 0, 30, 90, 180 and 365 days (it walks the whole tree), and a
    ``corpus`` entry counting the digits kept to retrain the recogniser
    (``digit_bank/samples``, ``numbers``) on their own -- no sweep deletes
    those, so they are worth watching apart from the rest.
    """
    dry_run = request_form.get("dry_run", "true").lower() != "false"
    include_strays = request_form.get("include_strays", "false").lower() == "true"
    include_empty_jobs = (
        request_form.get("include_empty_jobs", "false").lower() == "true"
    )
    with_usage = request_form.get("usage", "false").lower() == "true"
    try:
        min_age_hours = float(request_form.get("min_age_hours", "24"))
        # "nan" passed the >= 0 check below and "inf" overflowed int(): 500s
        if not math.isfinite(min_age_hours):
            raise ValueError(min_age_hours)
    except ValueError:
        return _error("min_age_hours is not a number.")
    if min_age_hours < 0:
        return _error("min_age_hours must be >= 0.")

    db = mongo["RMN"]
    min_age_seconds = int(min_age_hours * 3600)
    if dry_run:
        report = storage_cleanup.scan(storage, db, min_age_seconds)
    else:
        report = storage_cleanup.clean(
            storage,
            db,
            min_age_seconds,
            include_strays,
            delete_job=delete_job if include_empty_jobs else None,
        )
    report["dry_run"] = dry_run
    if with_usage:
        report["usage"] = storage_cleanup.usage(storage)
    print(
        "Storage sweep:",
        len(report["orphans"]),
        "orphan(s),",
        report["bytes"],
        "bytes,",
        len(report["empty_jobs"]),
        "empty job(s),",
        "dry run" if dry_run else "deleted",
    )
    return Response(response=json.dumps({"response": "OK", **report}), status=200)


def wake_executor():
    """Push an empty job: an idle executor wakes up and reads the queue."""
    redis.rpush("job_queue", "{}")
    return Response(response=json.dumps({"response": "OK"}), status=200)


def queue_length():
    """How many jobs wait for an executor."""
    return redis.llen("job_queue")
