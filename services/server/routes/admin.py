"""Operator commands, guarded by the shared admin key rather than a session."""

import json
import math

from flask import Blueprint, Response, request
from flask_cors import cross_origin
from auth import verify_admin
from context import mongo, redis, storage
from service import storage_cleanup
from service.job_cleanup import delete_job, delete_old_jobs
from service.template_service import TemplateService
from service.user_service import UserService
from utils.forms import form_int

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _negative(field):
    return Response(
        response=json.dumps({"response": f"Error: {field} must be >= 0."}),
        status=400,
    )


@bp.route("/delete/jobs", methods=["POST"])
@cross_origin()
@verify_admin
def admin_delete_jobs():
    request_form = request.form

    if "n_days_old" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: n_days_old not provided."}),
            status=400,
        )

    n_days_old = form_int(request_form, "n_days_old")
    # a negative age puts the cutoff in the future: every job would go
    if n_days_old < 0:
        return _negative("n_days_old")

    user_id = None
    if "username" in request_form:
        user_id = str(request_form["username"])
    elif "user_id" in request_form:
        user_id = str(request_form["user_id"])

    n = delete_old_jobs(n_days_old, user_id)

    #
    return Response(
        response=json.dumps({"response": "OK", "n_deleted_jobs": n}), status=200
    )


@bp.route("/signup", methods=["POST"])
@cross_origin()
@verify_admin
def admin_signup():
    db = mongo["RMN"]
    return UserService.signup(request, db)


@bp.route("/delete/tokens", methods=["POST"])
@cross_origin()
@verify_admin
def admin_delete_tokens():
    request_form = request.form
    user_id = None
    if "username" in request_form:
        user_id = str(request_form["username"])
    elif "user_id" in request_form:
        user_id = str(request_form["user_id"])
    n_days_old = form_int(request_form, "n_days_old", default=0)
    if n_days_old < 0:
        return _negative("n_days_old")
    db = mongo["RMN"]
    UserService.delete_tokens(user_id, n_days_old, db)
    return Response(response=json.dumps({"response": "OK"}), status=200)


@bp.route("/delete/user", methods=["POST"])
@cross_origin()
@verify_admin
def admin_delete_user():
    request_form = request.form

    if "username" not in request_form and "user_id" not in request_form:
        return Response(
            response=json.dumps(
                {
                    "response": "Error: username and user_id not provided. "
                    "Please one of these two fields."
                }
            ),
            status=400,
        )

    if "username" in request_form:
        user_id = str(request_form["username"])
    else:
        user_id = str(request_form["user_id"])
    #
    delete_old_jobs(user_id=user_id)

    #
    db = mongo["RMN"]
    TemplateService.delete_templates(user_id, db, storage)
    UserService.delete(user_id, db)

    #
    return Response(response=json.dumps({"response": "OK"}), status=200)


@bp.route("/users", methods=["POST"])
@cross_origin()
@verify_admin
def admin_users():
    db = mongo["RMN"]
    all_users = UserService.users(db)
    return Response(
        response=json.dumps({"response": "OK", "users": all_users}), status=200
    )


@bp.route("/change_password", methods=["POST"])
@cross_origin()
@verify_admin
def admin_change_password():
    db = mongo["RMN"]
    return UserService.change_password(request, db, False)


@bp.route("/template", methods=["POST"])
@cross_origin()
@verify_admin
def create_default_template():
    db = mongo["RMN"]
    return TemplateService.add_default_templates(
        request.form.get("user_id"), db, storage
    )


@bp.route("/storage/clean", methods=["POST"])
@cross_origin()
@verify_admin
def admin_clean_storage():
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
    request_form = request.form
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
        return Response(
            response=json.dumps({"response": "Error: min_age_hours is not a number."}),
            status=400,
        )
    if min_age_hours < 0:
        return Response(
            response=json.dumps({"response": "Error: min_age_hours must be >= 0."}),
            status=400,
        )

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


@bp.route("/executor", methods=["GET"])
@cross_origin()
@verify_admin
def admin_executor():
    redis.rpush("job_queue", "{}")
    return Response(response=json.dumps({"response": "OK"}), status=200)
