"""The operator commands of the webapp's admin page, for an Administrateur.

The same work as ``/admin/*`` (:mod:`service.operations`), reached with an
Administrateur's session instead of the shared key; nginx keeps refusing
``/api/admin/`` from outside.
"""

from flask import Blueprint, json, request
from flask_cors import cross_origin
from rmn_common import settings

from auth import verify_token
from context import mongo, redis, storage
from service import digit_bank, operations
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


@bp.route("/settings", methods=["GET"])
@cross_origin()
@verify_token(Role.ADMIN)
def get_settings(user_id):
    """The settings every user shares (see rmn_common.settings)."""
    collection = mongo["RMN"][settings.SETTINGS_COLLECTION]
    return Response(
        response=json.dumps(
            {
                "response": {
                    "saveVerifiedImages": settings.save_verified_images(collection)
                }
            }
        ),
        status=200,
    )


@bp.route("/settings", methods=["POST"])
@cross_origin()
@verify_token(Role.ADMIN)
def update_settings(user_id):
    """Change a shared setting: ``saveVerifiedImages`` (0 or 1), the digit bank."""
    value = request.form.get("saveVerifiedImages")
    if value not in ("0", "1"):
        return Response(
            response=json.dumps(
                {"response": "Error: saveVerifiedImages must be 0 or 1."}
            ),
            status=400,
        )
    settings.set_save_verified_images(
        mongo["RMN"][settings.SETTINGS_COLLECTION], value == "1"
    )
    print(f"Settings: {user_id} sets saveVerifiedImages to {value}.")
    return Response(
        response=json.dumps({"response": {"saveVerifiedImages": value == "1"}}),
        status=200,
    )


@bp.route("/digit-bank", methods=["GET"])
@cross_origin()
@verify_token(Role.ADMIN)
def get_digit_bank(user_id):
    """The digit bank, the model the executors run and the latest runs."""
    return Response(
        response=json.dumps({"response": digit_bank.overview(mongo["RMN"], storage)}),
        status=200,
    )


@bp.route("/digit-bank/run", methods=["POST"])
@cross_origin()
@verify_token(Role.ADMIN)
def run_digit_model(user_id):
    """Queue a run for the trainer worker: ``action`` is ``train`` or ``evaluate``.

    An evaluation scores the model in use, or with ``target`` the model a
    finished training wrote.
    """
    try:
        action = request.form.get("action")
        target = request.form.get("target") or None
        row = digit_bank.start_run(mongo["RMN"], redis, action, user_id, target)
    except ValueError as e:
        return Response(response=json.dumps({"response": str(e)}), status=400)
    if row is None:
        return Response(
            response=json.dumps({"response": "Une demande est déjà en cours."}),
            status=409,
        )
    print(f"Digit model: {user_id} queues a {row['action']} run ({row['run_id']}).")
    return Response(response=json.dumps({"response": row}), status=200)


@bp.route("/digit-bank/activate", methods=["POST"])
@cross_origin()
@verify_token(Role.ADMIN)
def activate_digit_model(user_id):
    """Have the executors run a trained model: ``run_id``, empty for the shipped one."""
    run_id = request.form.get("run_id", "")
    try:
        digit_bank.activate(mongo["RMN"], storage, run_id, user_id)
    except ValueError as e:
        return Response(response=json.dumps({"response": str(e)}), status=400)
    print(f"Digit model: {user_id} activates {run_id or 'the shipped model'}.")
    return Response(
        response=json.dumps({"response": digit_bank.overview(mongo["RMN"], storage)}),
        status=200,
    )


@bp.route("/digit-bank/delete", methods=["POST"])
@cross_origin()
@verify_token(Role.ADMIN)
def delete_digit_model_run(user_id):
    """Delete a finished run ``run_id``, and the model of a training not in use."""
    run_id = request.form.get("run_id", "")
    try:
        digit_bank.delete_run(mongo["RMN"], storage, run_id)
    except ValueError as e:
        return Response(response=json.dumps({"response": str(e)}), status=400)
    print(f"Digit model: {user_id} deletes the run {run_id}.")
    return Response(
        response=json.dumps({"response": digit_bank.overview(mongo["RMN"], storage)}),
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
    days = request.form.get("n_days_old")
    print(f"Job sweep: {user_id} deletes the jobs of {days} days and more.")
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
