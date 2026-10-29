"""Operator commands, guarded by the shared admin key rather than a session.

The work itself is in :mod:`service.operations`, which the admin page of the
webapp reaches through ``/manage/*`` with an Administrateur's session.
"""

from flask import json

from flask import Blueprint, request

from utils.responses import Response
from flask_cors import cross_origin
from auth import verify_admin
from context import mongo, storage
from service import operations
from service.template_service import TemplateService
from service.user_service import UserService

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/delete/jobs", methods=["POST"])
@cross_origin()
@verify_admin
def admin_delete_jobs():
    return operations.delete_jobs(request.form, operations._form_user(request.form))


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
    return operations.delete_tokens(request.form, operations._form_user(request.form))


@bp.route("/delete/user", methods=["POST"])
@cross_origin()
@verify_admin
def admin_delete_user():
    user_id = operations._form_user(request.form)
    if user_id is None:
        return Response(
            response=json.dumps(
                {
                    "response": "Error: username and user_id not provided. "
                    "Please one of these two fields."
                }
            ),
            status=400,
        )
    return operations.delete_account(user_id)


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
    """See :func:`service.operations.storage_sweep` for the form fields."""
    return operations.storage_sweep(request.form)


@bp.route("/executor", methods=["GET"])
@cross_origin()
@verify_admin
def admin_executor():
    return operations.wake_executor()
