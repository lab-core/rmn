"""Operator commands, guarded by the shared admin key rather than a session."""

import json
from flask import Blueprint, Response, request
from flask_cors import cross_origin
from auth import verify_admin
from context import mongo, redis, storage
from service import storage_cleanup
from service.job_cleanup import delete_old_jobs
from service.template_service import TemplateService
from service.user_service import UserService


bp = Blueprint("admin", __name__)


@bp.route("/admin/delete/jobs", methods=["POST"])
@cross_origin()
@verify_admin
def admin_delete_jobs():
    request_form = request.form

    if "n_days_old" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: n_days_old not provided."}),
            status=400,
        )

    #
    n_days_old = int(request_form["n_days_old"])

    user_id = None
    if "username" in request_form:
        user_id = str(request_form["username"])
    elif "user_id" in request_form:
        user_id = str(request_form["user_id"])

    n = delete_old_jobs(n_days_old, user_id)

    #
    return Response(response=json.dumps({"response": "OK", "n_deleted_jobs": n}), status=200)


@bp.route("/admin/signup", methods=["POST"])
@cross_origin()
@verify_admin
def admin_signup():
    db = mongo["RMN"]
    return UserService.signup(request, db)


@bp.route("/admin/delete/tokens", methods=["POST"])
@cross_origin()
@verify_admin
def admin_delete_tokens():
    request_form = request.form
    user_id = None
    if "username" in request_form:
        user_id = str(request_form["username"])
    elif "user_id" in request_form:
        user_id = str(request_form["user_id"])
    n_days_old = int(request_form["n_days_old"]) if "n_days_old" in request_form else 0
    db = mongo["RMN"]
    UserService.delete_tokens(user_id, n_days_old, db)
    return Response(
        response=json.dumps({"response": "OK"}),
        status=200
    )


@bp.route("/admin/delete/user", methods=["POST"])
@cross_origin()
@verify_admin
def admin_delete_user():
    request_form = request.form

    if "username" not in request_form and "user_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: username and user_id not provided. "
                                             "Please one of these two fields."}),
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


@bp.route("/admin/users", methods=["POST"])
@cross_origin()
@verify_admin
def admin_users():
    db = mongo["RMN"]
    all_users = UserService.users(db)
    return Response(response=json.dumps({"response": "OK", "users": all_users}), status=200)


@bp.route("/admin/change_password", methods=["POST"])
@cross_origin()
@verify_admin
def admin_change_password():
    db = mongo["RMN"]
    return UserService.change_password(request, db, False)


@bp.route("/admin/template", methods=["POST"])
@cross_origin()
@verify_admin
def create_default_template():
    db = mongo["RMN"]
    return TemplateService.add_default_templates(request.form.get('user_id'), db, storage)


@bp.route("/admin/storage/clean", methods=["POST"])
@cross_origin()
@verify_admin
def admin_clean_storage():
    """Report, and optionally delete, storage no database row owns any more.

    Form fields: ``dry_run`` (default true -- the sweep only reports),
    ``min_age_hours`` (default 24, paths touched more recently are skipped so
    the sweep cannot race an upload) and ``include_strays`` (default false --
    also delete paths under a known prefix that match no layout rule).
    """
    request_form = request.form
    dry_run = request_form.get("dry_run", "true").lower() != "false"
    include_strays = request_form.get("include_strays", "false").lower() == "true"
    try:
        min_age_hours = float(request_form.get("min_age_hours", "24"))
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
        report = storage_cleanup.clean(storage, db, min_age_seconds, include_strays)
    report["dry_run"] = dry_run
    print(
        "Storage sweep:", len(report["orphans"]), "orphan(s),",
        report["bytes"], "bytes,", "dry run" if dry_run else "deleted",
    )
    return Response(
        response=json.dumps({"response": "OK", **report}), status=200
    )


@bp.route("/admin/executor", methods=["GET"])
@cross_origin()
@verify_admin
def admin_executor():
    redis.rpush("job_queue", "{}")
    return Response(response=json.dumps({"response": "OK"}), status=200)
