"""Reading the student number off a copy, and correcting what was read."""

import json
import uuid
from flask import Blueprint, Response, request
from flask_cors import cross_origin
from rmn_common.status import Document_Status
from auth import verify_share_token, verify_token
from context import mongo, sio
from utils.forms import form_int


bp = Blueprint("matricules", __name__, url_prefix="/matricules")


@bp.route("/update", methods=["POST"])
@cross_origin()
@verify_share_token(question=False)
def update_matricule():
    request_form = request.form

    required_fields = ["job_id", "document_index", "matricule"]
    for field in required_fields:
        if field not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: {field} not provided."}),
                status=400,
            )

    job_id = str(request_form["job_id"])
    document_index = form_int(request_form, "document_index")
    matricule = str(request_form["matricule"])

    db = mongo["RMN"]
    db["job_documents"].update_one(
        {"job_id": job_id, "document_index": document_index},
        {"$set": {"matricule": matricule, "status": Document_Status.VALIDATED.value}}
    )

    # The teacher annotated the copy in the app and saved it without typing a
    # grade: the mark they drew is on the page now, so read it. Only this copy
    # is queued -- a save is one copy, not a question.
    user_id = db["eval_jobs"].find_one({"job_id": job_id})["user_id"]

    sio.emit(
        "doc_validated",
        json.dumps(
            {"job_id": job_id, "user_id": user_id, "document_index": document_index, "matricule": True}
        ),
    )

    return Response(response=json.dumps({"response": "OK"}), status=200)


@bp.route("/status/update", methods=["POST"])
@cross_origin()
@verify_share_token(question=False)
def update_matricule_status():
    request_form = request.form

    required_fields = ["job_id", "document_index", "status"]
    for field in required_fields:
        if field not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: {field} not provided."}),
                status=400,
            )

    job_id = str(request_form["job_id"])
    document_index = form_int(request_form, "document_index")
    status = str(request_form["status"])

    try:
        Document_Status(status)
    except ValueError:
        return Response(
            response=json.dumps({"response": f"Error: status {status} is invalid."}),
            status=400,
        )

    db = mongo["RMN"]
    db["job_documents"].update_one(
        {"job_id": job_id, "document_index": document_index},
        {"$set": {"status": status}}
    )

    user_id = db["eval_jobs"].find_one({"job_id": job_id})["user_id"]

    sio.emit(
        "doc_validated",
        json.dumps(
            {"job_id": job_id, "user_id": user_id, "document_index": document_index, "matricule": True}
        ),
    )

    return Response(response=json.dumps({"response": "OK"}), status=200)


@bp.route("/share", methods=["POST"])
@cross_origin()
@verify_token()
def share_matricule_verification(user_id):
    # Define db and collection used
    db = mongo["RMN"]
    collection = db["eval_jobs"]

    request_form = request.form
    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400
        )
    job_id = str(request_form["job_id"])

    host = request.headers.get('Host')
    if not host:
        return Response(
            response=json.dumps({"response": "Error: Host is not defined in the headers."}),
            status=400
        )

    job = collection.find_one({"job_id": job_id, "user_id": user_id})
    if job is None:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=404
        )

    if "share_token" not in job:
        token = str(uuid.uuid4())
        collection.update_one(
            {"job_id": job_id},
            {"$set": {"share_token": {"mat": token}}})
    elif "mat" not in job["share_token"]:
        token = str(uuid.uuid4())
        collection.update_one(
            {"job_id": job_id},
            {"$set": {"share_token.mat": token}})
    else:
        token = job["share_token"]["mat"]

    # a local host (possibly with a port, e.g. "localhost:8085") is served over
    # http; anything else sits behind the TLS reverse proxy
    hostname = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    protocol = "http" if hostname in ("0.0.0.0", "localhost", "127.0.0.1") else "https"
    share_url = f"{protocol}://{host}/matricule-validation/?job_id={job_id}&token={token}"

    resp = {
        "job_id": job["job_id"],
        "share_url": share_url,
        "groups": job.get("groups", [""])
    }
    return Response(response=json.dumps({"response": resp}), status=200)


@bp.route("/unshare", methods=["POST"])
@cross_origin()
@verify_token()
def unshare_matricule(user_id):
    # Define db and collection used
    db = mongo["RMN"]
    collection = db["eval_jobs"]

    request_form = request.form
    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400
        )
    job_id = str(request_form["job_id"])

    res = collection.update_one({"job_id": job_id, "user_id": user_id}, {"$unset": {f"share_token.mat": ""}})
    if res.matched_count == 0:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=404
        )

    return Response(response=json.dumps({"response": "OK"}), status=200)
