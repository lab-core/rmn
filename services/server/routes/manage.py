"""The operator commands of the webapp's admin page, for an Administrateur.

The same work as ``/admin/*`` (:mod:`service.operations`), reached with an
Administrateur's session instead of the shared key; nginx keeps refusing
``/api/admin/`` from outside.
"""

from flask import Blueprint, json, request
from flask_cors import cross_origin

from auth import verify_token
from service import operations
from service.user_service import Role
from utils.forms import form_int
from utils.responses import Response

bp = Blueprint("manage", __name__, url_prefix="/manage")


@bp.route("/status", methods=["GET"])
@cross_origin()
@verify_token(Role.ADMIN)
def status(user_id):
    return Response(
        response=json.dumps({"response": {"queue": operations.queue_length()}}),
        status=200,
    )


@bp.route("/storage/clean", methods=["POST"])
@cross_origin()
@verify_token(Role.ADMIN)
def clean_storage(user_id):
    """See :func:`service.operations.storage_sweep` for the form fields."""
    return operations.storage_sweep(request.form)


@bp.route("/delete/jobs", methods=["POST"])
@cross_origin()
@verify_token(Role.ADMIN)
def delete_jobs(user_id):
    """Delete every user's jobs at least ``n_days_old`` days old."""
    print(f"Job sweep: {user_id} deletes the jobs of {request.form.get('n_days_old')} days and more.")
    return operations.delete_jobs(request.form)


@bp.route("/delete/tokens", methods=["POST"])
@cross_origin()
@verify_token(Role.ADMIN)
def delete_tokens(user_id):
    """Delete every login token at least ``n_days_old`` days old (at least 1:
    0 would close the admin's own session with everyone else's)."""
    if form_int(request.form, "n_days_old", default=0) < 1:
        return Response(
            response=json.dumps({"response": "Error: n_days_old must be >= 1."}),
            status=400,
        )
    return operations.delete_tokens(request.form)
