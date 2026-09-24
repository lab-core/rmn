"""The output archive of a finished task, and the links that share it."""

import json
import os
import uuid
from flask import Blueprint, Response, request, send_file
from flask_cors import cross_origin
from rmn_common.status import Output_File
from auth import verify_share_token, verify_token
from context import TEMP_FOLDER, mongo, storage
from utils.uploads import temp_upload_path


bp = Blueprint("files", __name__, url_prefix="/files")


@bp.route("/share", methods=["POST"])
@cross_origin()
@verify_share_token(question=False, matricule=False)  # just token all
def share_archive():
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

    if "file" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: file not provided."}),
            status=400,
        )
    target_file = str(request_form["file"])

    zip_index = None
    if 'zip' in target_file:
        if "zip_index" not in request_form:
            return Response(
                response=json.dumps({"response": "Error: zip_index not provided."}),
                status=400,
            )
        zip_index = str(request_form["zip_index"])

    # Define db and collection used
    db = mongo["RMN"]
    output_collection = db["jobs_output"]
    job = output_collection.find_one({"job_id": job_id})

    if job is None:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} doesn't exist."}),
            status=404
        )

    if "share_token" not in job:
        token = str(uuid.uuid4())
        output_collection.update_one(
            {"job_id": job_id},
            {"$set": {"share_token": token}})
    else:
        token = job["share_token"]

    # a local host (possibly with a port, e.g. "localhost:8085") is served over
    # http; anything else sits behind the TLS reverse proxy
    hostname = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    protocol = "http" if hostname in ("0.0.0.0", "localhost", "127.0.0.1") else "https"
    share_url = f"{protocol}://{host}/api/file/download?job_id={job_id}&token={token}&file={target_file}"
    if zip_index:
        share_url += f"&zip_index={zip_index}"

    resp = {
        "job_id": job["job_id"],
        "share_url": share_url
    }
    return Response(response=json.dumps({"response": resp}), status=200)


@bp.route("/unshare", methods=["POST"])
@cross_origin()
@verify_token()
def unshare_file(user_id):
    # Define db and collection used
    db = mongo["RMN"]
    collection = db["jobs_output"]

    request_form = request.form
    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400
        )
    job_id = str(request_form["job_id"])

    # Get all jobs from DB
    res = collection.update_one({"job_id": job_id, "user_id": user_id}, {"$unset": {"share_token": ""}})
    if res.matched_count == 0:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=404
        )

    return Response(response=json.dumps({"response": "OK"}), status=200)


@bp.route("/download", methods=["GET", "POST"])
@cross_origin()
@verify_share_token()
def download_file():
    #
    if request.method == 'POST':
        request_form = request.form
    else:
        request_form = request.args

    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400,
        )

    if "file" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: file not provided."}),
            status=400,
        )

    #
    job_id = str(request_form["job_id"])
    target_file = str(request_form["file"])
    try:
        target_file = Output_File(target_file)
    except Exception as e:
        print(e)
        return Response(
            response=json.dumps(
                {"response": "Error: invalid value for 'file' param."}
            ),
            status=404,
        )
    if "zip_index" not in request_form and target_file == Output_File.ZIP_FILE:
        return Response(
            response=json.dumps({"response": "Error: zip_index not provided."}),
            status=400,
        )

    #
    db = mongo["RMN"]
    output_collection = db["jobs_output"]
    output_files = output_collection.find_one({"job_id": job_id})
    if not output_files:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} doesn't exist."}),
            status=404
        )

    #
    output_file_mapping_dict = {
        Output_File.NOTES_CSV_FILE: "notes_csv_file_id",
        Output_File.STATS_PDF_FILE: "stats_file_id",
        Output_File.PREVIEW_FILE: "preview_file_id",
        Output_File.ZIP_FILE: "zip_id_list",
    }

    target_output_file = output_file_mapping_dict[target_file]

    file_id = output_files[target_output_file]
    if target_file == Output_File.ZIP_FILE:
        zip_index = int(request_form["zip_index"])
        file_id = file_id[zip_index]

    if not os.path.exists(TEMP_FOLDER):
        os.makedirs(TEMP_FOLDER)

    # Save file to local
    filename = request_form.get('filename')
    print("File to send", file_id, filename)
    filepath = str(temp_upload_path(file_id.split(os.sep)[-1]))
    storage.copy_from(file_id, filepath)
    file_send = send_file(filepath, download_name=filename, as_attachment=True)
    os.remove(filepath)

    return file_send
