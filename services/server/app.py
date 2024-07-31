import glob
import re
from service.template_service import TemplateService
from service.user_service import UserService, Role
from flask import Flask, request, Response, json, send_file, after_this_request
from flask_cors import CORS, cross_origin
from werkzeug.utils import secure_filename
from pathlib import Path
from utils.utils import Job_Status, Output_File, Document_Status
from utils.storage import Storage
from utils.clients import redis_client, socketio_client, mongo_client
from utils.zip import update_zip
import datetime as dt
from io import FileIO
from service.front_page_service import FrontPageHandler
from threading import Thread
from zipfile import ZipFile

import uuid
import os
import json
import shutil
import time
import tempfile
from functools import wraps


app = Flask(__name__)
cors = CORS(app)
app.config["CORS_HEADERS"] = "Content-Type"

mongo = mongo_client()
redis = redis_client()
storage = Storage()
# exec_storage = Storage(f"C:{os.sep}Users{os.sep}edgar{os.sep}rmn{os.sep}services{os.sep}executor{os.sep}storage")

ROOT_DIR = Path(__file__).resolve().parent
TEMP_FOLDER = ROOT_DIR.joinpath("temp")
VALIDATE_TEMP_FOLDER = ROOT_DIR.joinpath("validate_temp_folder")
FRONT_PAGE_TEMP_FOLDER = ROOT_DIR.joinpath("front_page_temp")
LATEX_INPUT_FILE = ROOT_DIR.joinpath("data.tex")


def check_token(form, role=None):
    # check if token provided
    if "token" not in form:
        return Response(
            response=json.dumps({"response": "Error: token not provided."}),
            status=401,
        ), None
    # check if token valid
    db = mongo["RMN"]
    token = form['token']
    valid, username = UserService.verify_token(token, db, role)
    if not valid:
        return Response(
            response=json.dumps({"response": "Error: token not valid. Please login."}),
            status=401,
        ), None
    if ("user_id" in form and form["user_id"] != username) or \
            ("username" in form and form["username"] != username):
        print(f"Error: token belongs to username {username}.")
        return Response(
            response=json.dumps({"response": "Error: token belongs to another username."}),
            status=401,
        ), None

    return None, username


def verify_token(role=None):
    def _verify_token(f):
        @wraps(f)
        def __verify_token(*args, **kwargs):
            # check if token valid
            resp, user_id = check_token(request.form, role)
            if resp:
                return resp
            return f(user_id)
        return __verify_token
    return _verify_token


def verify_share_token(question=True, matricule=True, return_validity=False):
    def _verify_token(f):
        @wraps(f)
        def __verify_token(*args, **kwargs):
            # check if any token share token provided
            if "job_id" not in request.form:
                print("Error: job_id not provided.")
                return Response(
                    response=json.dumps({"response": "Error: job_id not provided."}),
                    status=401,
                )
            job_id = request.form["job_id"]
            db = mongo["RMN"]

            # check if token valid
            resp, user_id = check_token(request.form)
            # if resp is None => valid token
            if resp is None:
                job = db["eval_jobs"].find_one({"job_id": job_id, "user_id": user_id})
                if job is None:
                    print(f"Error: job {job_id} for user {user_id} doesn't exist.")
                    job = db["eval_jobs"].find_one({"job_id": job_id})
                    if job:
                        print("Found job:", job)
                    # if there is a share token, try it after
                    if "share_token" not in request.form:
                        return Response(
                            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
                            status=401
                        )
                elif return_validity:
                    return f(None)
                else:
                    return f()
            # check if any token share token provided
            if "share_token" not in request.form:
                return Response(
                    response=json.dumps({"response": "Error: token not provided."}),
                    status=401,
                )
            # check if share token valid
            db = mongo["RMN"]
            token = request.form["share_token"]

            keys = []
            if question:
                keys.append("all")
                if "question_index" in request.form:
                    keys.append(request.form["question_index"])
            if matricule:
                keys.append("mat")

            validity = None
            job = db["eval_jobs"].find_one({"job_id": job_id})
            if job:
                for k, t in job.get("share_token", {}).items():
                    if k in keys and t == token:
                        validity = k
            if validity is None:
                print("Error: share token (", token, ") not valid for", job_id, "and keys", keys)
                return Response(
                    response=json.dumps({"response": "Error: share token not valid."}),
                    status=401,
                )
            if return_validity:
                return f(validity)
            else:
                return f()
        return __verify_token
    return _verify_token


@app.route(os.sep)
def say_hello():
    return "<h1>Hi Andy, I'm on fire !</h1>"


@app.route("/login", methods=["POST"])
@cross_origin()
def login():
    db = mongo["RMN"]
    return UserService.login(request, db)


@app.route("/signup", methods=["POST"])
@cross_origin()
@verify_token(Role.ADMIN)
def signup(user_id):
    db = mongo["RMN"]
    return UserService.signup(request, db)


@app.route("/updateSaveVerifiedImages", methods=["PUT"])
@cross_origin()
@verify_token()
def update_user(user_id):
    db = mongo["RMN"]
    return UserService.update_save_verified_images(request, db)

@app.route("/updateMoodleStructureInd", methods=["PUT"])
@cross_origin()
@verify_token()
def update_moodle_structure_ind(user_id):
    db = mongo["RMN"]
    return UserService.update_moodle_structure_ind(request, db)


@app.route("/password", methods=["POST"])
@cross_origin()
@verify_token()
def change_password(user_id):
    db = mongo["RMN"]
    return UserService.change_password(request, db, True)


@app.route("/evaluate", methods=["POST"])
@cross_origin()
@verify_token()
def evaluate(user_id):
    request_form = request.form

    required_fields = [
        "front_template_id",
        "regular_template_id",
        "n_pages_per_question",
        "n_max_points_per_question",
        "bonus_enabled_map",
        "job_name",
        "front_template_name",
        "regular_template_name",
        "statistics_for_students"
    ]

    for field in required_fields:
        if field not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: {field} not provided."}),
                status=400,
            )

    if not request.files:
        return Response(
            response=json.dumps({"response": "Error: No files provided."}),
            status=400,
        )

    required_files = [
        "notes_csv_file",
        "zip_file"
    ]

    for file_field in required_files:
        if file_field not in request.files:
            return Response(
                response=json.dumps({"response": f"Error: {file_field} not provided."}),
                status=400,
            )

    front_template_id = str(request_form["front_template_id"])
    regular_template_id = str(request_form["regular_template_id"])
    front_template_name = str(request_form["front_template_name"])
    regular_template_name = str(request_form["regular_template_name"])
    job_name = str(request_form["job_name"])
    statistics_for_students = request_form["statistics_for_students"].lower() == "true"
    n_pages_per_question = json.loads(request_form["n_pages_per_question"])
    n_max_points_per_question = json.loads(request_form["n_max_points_per_question"])
    bonus_enabled_map = json.loads(request_form["bonus_enabled_map"])

    db = mongo["RMN"]
    collection = db["eval_jobs"]

    job_id = str(uuid.uuid4())

    path_on_cloud_zip = f"zips{os.sep}"
    zip_file_id = f"{path_on_cloud_zip}{job_id}.zip"

    path_on_cloud_csv = f"csv{os.sep}"
    notes_file_id = f"{path_on_cloud_csv}{job_id}.csv"

    job = {
        "job_id": job_id,
        "job_name": job_name,
        "user_id": user_id,
        "front_template_id": front_template_id,
        "regular_template_id": regular_template_id,
        "front_template_name": front_template_name,
        "regular_template_name": regular_template_name,
        "queued_time": dt.datetime.utcnow(),  # dt.datetime.now(dt.UTC)
        "job_status": Job_Status.SPLIT.value,
        "retry": 0,
        "notes_file_id": notes_file_id,
        "zip_file_id": zip_file_id,
        "n_pages_per_question": n_pages_per_question,
        "n_max_points_per_question": n_max_points_per_question,
        "bonus_enabled_map": bonus_enabled_map,
        "students_list": [],
        "statistics_for_students": statistics_for_students
    }

    try:
        collection.insert_one(job)
    except Exception as e:
        print(e)
        return Response(
            response=json.dumps({"response": "Error: Failed to insert in MongoDB."}),
            status=500,
        )

    if not os.path.exists(TEMP_FOLDER):
        os.makedirs(TEMP_FOLDER)
    try:
        # only for a zip with a folder for each student
        notes_csv_file = request.files.get("notes_csv_file")
        notes_csv_file_name = secure_filename(notes_csv_file.filename)
        notes_csv_file.save(FileIO(TEMP_FOLDER.joinpath(notes_csv_file_name), "wb"))

        zip_file = request.files.get("zip_file")
        zip_file_name = secure_filename(zip_file.filename)

        with open(str(TEMP_FOLDER.joinpath(zip_file_name)), "wb") as f_out:
            file_content = zip_file.stream.read()
            f_out.write(file_content)

    except Exception as e:
        print(e)
        return Response(response="Error: Failed to download files.", status=500)

    # Create SocketIO connection
    sio = socketio_client()
    sio.emit(
        "job_status",
        json.dumps(
            {"job_id": job_id, "status": Job_Status.SPLIT.value, "user_id": user_id}
        ),
    )

    thread = Thread(target=evaluate_thread,
                    kwargs={
                        "job_id": job_id,
                        "notes_file_id": notes_file_id,
                        "zip_file_id": zip_file_id,
                        "job": job,
                        "user_id": user_id,
                        "zip_file_name": zip_file_name,
                        "notes_csv_file_name": notes_csv_file_name
                    })
    thread.start()

    return Response(response=json.dumps({"response": "OK"}), status=200)


def evaluate_thread(job_id, notes_file_id, zip_file_id, job, user_id, zip_file_name, notes_csv_file_name):
    try:
        file_name = str(TEMP_FOLDER.joinpath(zip_file_name))
        storage.move_to(file_name, zip_file_id)

        file_name = str(TEMP_FOLDER.joinpath(notes_csv_file_name))
        storage.move_to(file_name, notes_file_id)
    except Exception as e:
        print("Error when preparing job to be submitted for evaluation.")
        print(e)

        db = mongo["RMN"]
        collection_eval_jobs = db["eval_jobs"]
        collection_eval_jobs.update_one(
                {"job_id": job_id},
                {
                    "$set": {
                        "job_status": Job_Status.ERROR.value,
                    }
                },
            )

        # Create SocketIO connection
        sio = socketio_client()
        sio.emit(
            "job_status",
            json.dumps(
                {
                    "job_id": job_id,
                    "user_id": user_id,
                    "status": Job_Status.ERROR.value,
                }
            ),
        )
        exit()

    # add to Redis Queue
    redis.rpush("job_queue", json.dumps({"job_id": job["job_id"]}))


@app.route("/template", methods=["POST"])
@cross_origin()
@verify_token()
def create_template(user_id):
    db = mongo["RMN"]
    return TemplateService.create_template(request, db, storage)


@app.route("/user/template", methods=["POST"])
@cross_origin()
@verify_token()
def get_all_template_info(user_id):
    db = mongo["RMN"]
    return TemplateService.get_all_template_info(request, db)


@app.route("/template/delete", methods=["POST"])
@cross_origin()
@verify_token()
def delete_template(user_id):
    db = mongo["RMN"]
    return TemplateService.delete_template(request, db, storage)


@app.route("/template/info", methods=["POST"])
@cross_origin()
@verify_token()
def get_template_info(user_id):
    db = mongo["RMN"]
    return TemplateService.get_template_info(request, db)


@app.route("/template/download", methods=["POST"])
@cross_origin()
@verify_token()
def download_template(user_id):
    db = mongo["RMN"]
    return TemplateService.download_template_file(request, db, storage)


@app.route("/template/modify", methods=["POST"])
@cross_origin()
@verify_token()
def modify_template(user_id):
    db = mongo["RMN"]
    return TemplateService.change_template_info(request, db)


@app.route("/jobs", methods=["POST"])
@cross_origin()
@verify_token()
def get_jobs(user_id):
    # Define db and collection used
    db = mongo["RMN"]
    collection = db["eval_jobs"]

    # Get all jobs from DB
    jobs = [j for j in collection.find({"user_id": user_id})]

    #
    resp = [
        {
            "job_id": job["job_id"],
            "front_template_id": job["front_template_id"],
            "regular_template_id": job["regular_template_id"],
            "queued_time": str(job["queued_time"]),
            "job_status": job["job_status"],
            "job_name": job["job_name"],
            "front_template_name": job["front_template_name"],
            "regular_template_name": job["regular_template_name"],
            "job_infos": job.get("job_infos", "")
        }
        for job in jobs
    ]

    # wake up workers in case some jobs died
    max_alive = dt.datetime.utcnow() - dt.timedelta(seconds=120)  # dt.datetime.now(dt.UTC)

    def requeue(job_id, c_status, n_status):
        print("Resubmit job", job_id)
        # change status to ensure that a job is not resubmitted several times
        res = collection.update_one(
            {"job_id": job_id, "job_status": c_status},
            {"$inc": {"retry": 1}, "$set": {"job_status": n_status}}
        )
        if res.matched_count > 0:
           redis.lpush("job_queue", json.dumps({"job_id": job_id}))

    for job in jobs:
        if job["job_status"] == Job_Status.RUN.value and job["alive_time"] < max_alive:
            requeue(job["job_id"], Job_Status.RUN.value, Job_Status.QUEUED.value)

    #
    return Response(response=json.dumps({"response": resp}), status=200)


@app.route("/job", methods=["POST"])
@cross_origin()
@verify_share_token()
def get_job():
    # Define db and collection used
    db = mongo["RMN"]
    collection = db["eval_jobs"]

    request_form = request.form
    job_id = str(request_form["job_id"])

    # Get all jobs from DB
    job = collection.find_one({"job_id": job_id})
    if job is None:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} doesn't exist."}),
            status=400
        )

    #
    resp = {
        "job_id": job["job_id"],
        "front_template_id": job["front_template_id"],
        "regular_template_id": job["regular_template_id"],
        "queued_time": str(job["queued_time"]),
        "job_status": job["job_status"],
        "job_name": job["job_name"],
        "front_template_name": job["front_template_name"],
        "regular_template_name": job["regular_template_name"],
        "students_list": job["students_list"],
        "job_infos": job.get("job_infos", ""),
        "n_max_points_per_question": job["n_max_points_per_question"],
        "n_pages_per_question": job["n_pages_per_question"],
        "bonus_enabled_map": job["bonus_enabled_map"]
    }
    return Response(response=json.dumps({"response": resp}), status=200)


@app.route("/job/share", methods=["POST"])
@cross_origin()
@verify_token()
def share_job(user_id):
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

    # if "question_index" not in request_form:
    #     return Response(
    #         response=json.dumps({"response": "Error: question_index not provided."}),
    #         status=400
    #     )
    question_index = request_form.get("question_index")

    host = request.headers.get('Host')
    if not host:
        return Response(
            response=json.dumps({"response": "Error: Host is not defined in the headers."}),
            status=400
        )

    # Get all jobs from DB
    job = collection.find_one({"job_id": job_id, "user_id": user_id})
    if job is None:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=400
        )

    key = question_index if question_index else "all"
    if "share_token" not in job:
        token = str(uuid.uuid4())
        collection.update_one(
            {"job_id": job_id},
            {"$set": {"share_token": {key: token}}})
    elif key not in job["share_token"]:
        token = str(uuid.uuid4())
        collection.update_one(
            {"job_id": job_id},
            {"$set": {f"share_token.{key}": token}})
    else:
        token = job["share_token"][key]

    proto = "http" if host == "0.0.0.0" or host == "localhost" else "https"
    if question_index:
        share_url = f"{proto}://{host}/task-validation/?job_id={job_id}&token={token}&question_index={question_index}"
    else:
        share_url = f"{proto}://{host}/task-validation/?job_id={job_id}&token={token}"

    #
    resp = {
        "job_id": job["job_id"],
        "share_url": share_url
    }
    return Response(response=json.dumps({"response": resp}), status=200)


@app.route("/job/unshare", methods=["POST"])
@cross_origin()
@verify_token()
def unshare_job(user_id):
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

    # Get all jobs from DB
    if "questions" in request.form:
        key = request_form.get("question_index", "all")
    else:
        key = "mat"
    res = collection.update_one({"job_id": job_id, "user_id": user_id}, {"$unset": {f"share_token.{key}": ""}})
    if res.matched_count == 0:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=400
        )

    return Response(response=json.dumps({"response": "OK"}), status=200)

@app.route("/job/ignore", methods=["POST"])
@cross_origin()
@verify_token()
def ignore_job(user_id):
    request_form = request.form
    #
    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400,
        )

    job_id = str(request_form["job_id"])
    db = mongo["RMN"]
    db["eval_jobs"].update_one(
            {"job_id": job_id},
            {
                "$set": {"job_status": Job_Status.IGNORED.value},
                "$unset": {"job_infos": ""}
            },
    )

    # delete incorrect_files
    storage.remove_tree(os.path.join("incorrect_files", job_id))

    redis.rpush("job_queue", json.dumps({"job_id": job_id}))

    return Response(response=json.dumps({"response": "OK"}), status=200)


@app.route("/job/continue", methods=["POST"])
@cross_origin()
@verify_token()
def continue_job(user_id):
    request_form = request.form
    job_id = str(request_form["job_id"])

    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400,
        )

    if not request.files:
        return Response(
            response=json.dumps({"response": "Error: No files provided."}),
            status=400,
        )

    # replacing files in zip
    db = mongo["RMN"]
    collection_eval_jobs = db["eval_jobs"]
    job = collection_eval_jobs.find_one({"job_id": job_id})

    if job["job_status"] != Job_Status.RETRY.value:
        return Response(
            response=json.dumps({"response": f"Error: job status is not {Job_Status.RETRY.value}."}),
            status=400,
        )

    pdf_files = []
    for f in request.files.values():
        file_path = os.path.join("/tmp", f.filename)
        f.save(file_path)
        pdf_files.append(file_path)
    thread = Thread(target=continue_thread, args=[job_id, pdf_files])
    thread.start()

    # set status to CORRECTED
    collection_eval_jobs.update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "job_status": Job_Status.CORRECTED.value,
                }
            },
    )

    return Response(response=json.dumps({"response": "OK"}), status=200)


def continue_thread(job_id, pdf_files):
    zip_path = storage.abs_path(os.path.join("zips", f"{job_id}.zip"))
    update_zip(zip_path, pdf_files, f'/tmp/zip_contents_{job_id}')

    # removing questions pdfs
    storage.remove_tree(os.path.join("documents", job_id))
    storage.remove_tree(os.path.join("incorrect_files", job_id))

    # removing files in database
    db = mongo["RMN"]
    db["job_documents"].delete_many({"job_id": job_id})
    db["job_questions"].delete_many({"job_id": job_id})

    # add to Redis Queue
    redis.rpush("job_queue", json.dumps({"job_id": job_id}))


@app.route("/incorrect/download", methods=["POST"])
@cross_origin()
@verify_token()
def download_incorrect_files(user_id):
    request_form = request.form
    #
    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400,
        )

    #
    if "file" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: file not provided."}),
            status=400,
        )

    #
    job_id = str(request_form["job_id"])
    target_file = str(request_form["file"])
    file_path = os.path.join('incorrect_files', job_id, target_file)
    file_send = send_file(storage.abs_path(file_path))

    return file_send

@app.route("/file/download", methods=["POST"])
@cross_origin()
@verify_token()
def download_file(user_id):
    #
    request_form = request.form

    print("RECEIVED FORM DATA:", request_form)

    #
    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400,
        )

    #
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
            status=400,
        )
    if "zip_index" not in request_form and target_file == Output_File.ZIP_FILE:
        return Response(
            response=json.dumps({"response": "Error: zip_index not provided."}),
            status=400,
        )

    #
    db = mongo["RMN"]
    output_collection = db["jobs_output"]
    output_files = output_collection.find_one({"job_id": job_id, "user_id": user_id})
    if not output_files:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=400
        )

    #
    output_file_mapping_dict = {
        Output_File.NOTES_CSV_FILE: "notes_csv_file_id",
        Output_File.STATS_PDF_FILE: "stats_file_id",
        Output_File.PREVIEW_FILE: "preview_file_id",
        Output_File.ZIP_FILE: "moodle_zip_id_list",
    }

    target_output_file = output_file_mapping_dict[target_file]

    file_id = output_files[target_output_file]

    if target_file == Output_File.ZIP_FILE:
        zip_index = int(request_form["zip_index"])
        file_id = output_files[target_output_file][zip_index]

    if not os.path.exists(TEMP_FOLDER):
        os.makedirs(TEMP_FOLDER)

    # Save file to local
    print("File to send", file_id)
    filepath = str(TEMP_FOLDER.joinpath(file_id.split(os.sep)[-1]))
    storage.copy_from(file_id, filepath)
    file_send = send_file(filepath)
    os.remove(filepath)

    return file_send

@app.route("/job/batch/info", methods=["POST"])
@cross_origin()
@verify_token()
def get_info_zip(user_id):
    request_form = request.form

    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400,
        )
    #
    job_id = str(request_form["job_id"])

    #
    db = mongo["RMN"]
    output_collection = db["jobs_output"]

    #
    output_files = output_collection.find_one({"job_id": job_id, "user_id": user_id})
    if not output_files:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=400
        )
    #
    resp = len(output_files["moodle_zip_id_list"])

    #
    return Response(response=json.dumps({"response": resp}), status=200)

@app.route("/matricule/update", methods=["POST"])
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
    document_index = int(request_form["document_index"])
    matricule = str(request_form["matricule"])

    db = mongo["RMN"]
    db["job_documents"].update_one(
        {"job_id": job_id, "document_index": document_index},
        {"$set": {"matricule": matricule, "status": Document_Status.VALIDATED.value}}
    )

    user_id = db["eval_jobs"].find_one({"job_id": job_id})["user_id"]

    sio = socketio_client()
    sio.emit(
        "doc_validated",
        json.dumps(
            {"job_id": job_id, "user_id": user_id, "document_index": document_index, "matricule": matricule}
        ),
    )

    return Response(response=json.dumps({"response": "OK"}), status=200)


@app.route("/matricule/share", methods=["POST"])
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

    if "user_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: user_id not provided."}),
            status=400
        )
    user_id = str(request_form["user_id"])

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
            status=400
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

    protocol = "http" if host == "0.0.0.0" or host == "localhost" else "https"
    share_url = f"{protocol}://{host}/matricule-validation/?job_id={job_id}&token={token}"

    resp = {
        "job_id": job["job_id"],
        "share_url": share_url
    }
    return Response(response=json.dumps({"response": resp}), status=200)

@app.route("/documents", methods=["POST"])
@cross_origin()
@verify_share_token(return_validity=True)
def get_documents(validity):
    request_form = request.form
    job_id = str(request_form["job_id"])

    if not job_id:
        return Response(response=json.dumps({"Error": "job_id is missing"}), status=400)

    #
    db = mongo["RMN"]
    query = {"job_id": job_id}
    if request_form.get("documents_indices"):
        query["document_index"] = {"$in": json.loads(request_form["documents_indices"])}

    if request_form.get("questions") is not None:
        if validity == "mat":
            return Response(response=json.dumps({"Error": "You don't have access to these questions"}), status=400)
        question = None
        if validity is not None and validity != "all":
            question = f"Q{validity}"
        docs = db["job_questions"].find(query)
        count = db["job_questions"].count_documents(query)
        resp = [
            {
                "job_id": doc["job_id"],
                "document_index": doc["document_index"],
                "status": doc["status"],
                "filename": doc["filename"],
                "question_index": doc["question_index"],
                "question": doc["question"],
                "basename": doc["basename"],
                "grade": doc["grade"],
                "n_total_doc": count
            }
            for doc in docs if question is None or doc["question"] == question
        ]
        resp = sorted(resp, key=lambda k: k["document_index"])
        if resp and resp[-1]["document_index"] - resp[0]["document_index"] != len(resp) - 1:
            print(resp)
            print(resp[-1]["document_index"], "-", resp[0]["document_index"], " != ", len(resp) - 1)
            return Response(response=json.dumps({"Error": "The indices are not consecutive and increasing"}), status=400)
    else:
        if validity is not None and validity != "mat":
            return Response(response=json.dumps({"Error": "You don't have access to these documents"}), status=400)
        count = db["job_documents"].count_documents(query)
        docs = db["job_documents"].find(query)
        resp = [
            {
                "job_id": doc["job_id"],
                "document_index": doc["document_index"],
                "grades": doc["grades"],
                "matricule": doc["matricule"],
                "filename": doc["filename"],
                "status": doc["status"],
                "exec_time": doc["execution_time"],
                "n_total_doc": count,
                "group": doc.get("group", "")
            }
            for doc in docs
        ]

    #
    return Response(response=json.dumps({"response": resp}), status=200)


@app.route("/documents/update", methods=["POST"])
@cross_origin()
@verify_share_token(matricule=False)
def update_document():
    request_form = request.form
    required_fields = ["job_id", "document_index", "grades", "status"]
    for field in required_fields:
        if field not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: {field} not provided."}),
                status=400,
            )

    job_id = str(request_form["job_id"])
    document_index = int(request_form["document_index"])
    grades = [float(g) for g in json.loads(request_form["grades"])]

    # update the database
    db = mongo["RMN"]
    # first update question and job if any
    if "question_index" in request_form:
        grade = grades[0]
        q_doc = db["job_questions"].find_one_and_update(
            {"job_id": job_id, "document_index": document_index},
            {"$set": {
                "status": Document_Status.VALIDATED.value,
                "grade": grade
            }}
        )
        if q_doc is None:
            return Response(response=json.dumps({"response": f"Error: question {document_index} not found."}),
                            status=400)

        q_index = int(request_form["question_index"]) - 1
        r = db["job_documents"].update_one(
            {"job_id": job_id, "filename": q_doc["basename"]},
            {"$set": {
                f"grades.{q_index}": grade
            }}
        )
        if not r:
            return Response(response=json.dumps({"response": "Error: document %s not found." % q_doc["basename"]}),
                            status=400)
    else:
        grades = [float(g) for g in request_form["grades"]]
        r = db["job_documents"].update_one(
            {"job_id": job_id, "document_index": document_index},
            {"$set": {
                "status": Document_Status.VALIDATED.value,
                "grades": grades
            }}
        )
        return Response(response=json.dumps({"response": f"Error: document {document_index} not found."}),
                        status=400)

    # replacing the previous file by the new one in storage if any
    if "file" in request.files:
        file = request.files["file"]
        file_name = secure_filename(file.filename)

        last_underscore_index = file_name.rfind('_')
        extension_index = file_name.rfind('.pdf')
        question = file_name[last_underscore_index + 1:extension_index]

        file_path = os.path.join('documents', job_id, question, file_name)
        print("file path ", storage.abs_path(file_path))
        # save with default name as well as the latest version
        abs_filename = storage.abs_path(file_path)
        file.save(abs_filename)
        save_new_version(abs_filename)

    user_id = db["eval_jobs"].find_one({"job_id": job_id})["user_id"]

    sio = socketio_client()
    sio.emit(
        "doc_validated",
        json.dumps(
            {"job_id": job_id, "user_id": user_id, "document_index": document_index, "questions": True}
        ),
    )

    return Response(response=json.dumps({"response": "OK"}), status=200)


# @app.route("/documents/grade_all", methods=["POST"])
# @cross_origin()
# @verify_token()
# def grade_all_documents():
#     request_form = request.form
#
#     if "job_id" not in request_form:
#         return Response(
#             response=json.dumps({"response": "Error: job_id not provided."}),
#             status=400,
#         )
#
#     if "copies_informations" not in request_form:
#         return Response(
#             response=json.dumps({"response": "Error: copies_informations not provided."}),
#             status=400,
#         )
#
#     job_id = str(request_form["job_id"])
#
#     db = mongo["RMN"]
#
#     copies_informations = json.loads(request_form["copies_informations"])
#     collection_eval_jobs = db["eval_jobs"]
#     collection_eval_jobs.update_one(
#         {"job_id": job_id},
#         {"$set": {
#             "copies_informations": copies_informations,
#         }}
#     )
#
#     return Response(response=json.dumps({"response": "OK"}), status=200)

@app.route("/documents/replace", methods=["POST"])
@cross_origin()
@verify_share_token(matricule=False)
def replace_document():
    request_form = request.form
    request_files = request.files

    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400,
        )

    if "file" not in request_files:
        return Response(
            response=json.dumps({"response": "Error: file not provided."}),
            status=400,
        )

    job_id = str(request_form["job_id"])

    file = request_files["file"]
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_file.write(file.read())
        temp_file.flush()

        with ZipFile(temp_file.name, 'r') as zip_file:
            for file_info in zip_file.infolist():
                if file_info.filename.endswith(".pdf"):
                    extracted_path = zip_file.extract(file_info, path=TEMP_FOLDER)

                    # extracting question number from the filename
                    question_number = re.search(r'_Q(\d+)\.pdf', file_info.filename)
                    if question_number:
                        question_folder = "Q%d" % question_number.group(1)

                        storage_path = os.path.join('documents', job_id, question_folder, os.path.basename(file_info.filename))
                        final_destination = storage.abs_path(storage_path)

                        if not os.path.exists(os.path.dirname(final_destination)):
                            os.makedirs(os.path.dirname(final_destination), exist_ok=True)

                        # moving the extracted file to the final destination
                        shutil.move(extracted_path, final_destination)
                        print("Moved to:", final_destination)
                        save_new_version(final_destination)

    return Response(response=json.dumps({"response": "OK"}), status=200)


def version_basename(filename):
    version_dir = os.path.join(os.path.dirname(filename), "versions")
    version_name = os.path.basename(filename).rsplit(".", 1)[0]
    return os.path.join(version_dir, version_name)


def save_new_version(filename, version=None):
    version_base = version_basename(filename)
    all_versions = glob.glob(version_base+"-*.pdf")

    # create backup of the file if version does not already exist
    if version is None or version >= len(all_versions):
        shutil.copy(filename, version_base + "-%d.pdf" % len(all_versions))


@app.route("/document/download", methods=["POST"])
@cross_origin()
@verify_share_token(return_validity=True)
def download_document(validity):
    request_form = request.form

    if "document_index" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: document_index not provided."}),
            status=400,
        )

    job_id = str(request_form["job_id"])
    document_index = int(request_form["document_index"])

    db = mongo["RMN"]
    if request_form.get("questions") is not None:
        if validity == "mat":
            return Response(response=json.dumps({"Error": "You don't have access to this question"}), status=400)

        question_collection = db["job_questions"]
        doc = question_collection.find_one({"job_id": job_id, "document_index": document_index})
        if doc is None:
            return Response(
                response=json.dumps({"response": "No document found!"}),
                status=404,
            )

        if validity is not None and validity != "all" and doc["question"] != f"Q{validity}":
            return Response(response=json.dumps({"Error": "You don't have access to this question"}), status=400)

        # add the right version if requested
        file_path = doc["rel_filepath"]
        if "document_version" in request_form:
            try:
                version_name = version_basename(file_path) \
                               + "-%s.pdf" % request_form["document_version"]
                storage.copy_from(version_name, file_path)
            except ValueError:
                # if cannot find this version use default one (generally the last one)
                storage.copy_from(file_path, file_path)
        else:
            storage.copy_from(file_path, file_path)
    else:
        if validity is not None and validity != "mat":
            return Response(response=json.dumps({"Error": "You don't have access to this question"}), status=400)
        doc = db["job_documents"].find_one({"job_id": job_id, "document_index": document_index})
        if doc is None:
            return Response(
                response=json.dumps({"response": "No document found!"}),
                status=404,
            )

        file_path = doc["rel_filepath"]
        storage.copy_from(file_path, file_path)

    print("document_file: ", doc)
    file_send = send_file(file_path)

    time.sleep(0.1)

    @after_this_request
    def add_close_action(response):
        try:
            os.remove(file_path)
        except Exception as e:
            print(e)
        return response

    return file_send


@app.route("/document/last_version", methods=["POST"])
@cross_origin()
@verify_share_token()
def last_version_document():
    request_form = request.form
    if "document_index" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: document_index not provided."}),
            status=400,
        )

    job_id = str(request_form["job_id"])
    document_index = int(request_form["document_index"])

    db = mongo["RMN"]
    question_collection = db["job_questions"]
    question_file = question_collection.find_one({"job_id": job_id, "document_index": document_index})
    if question_file is None:
        return Response(
            response=json.dumps({"response": "No document found!"}),
            status=404,
        )

    version_base = version_basename(question_file["rel_filepath"])
    filename_base = storage.abs_path(version_base)
    print("file_base", filename_base)
    all_versions = glob.glob(filename_base + "-*.pdf")

    return Response(response=json.dumps({"last_version": len(all_versions) - 1}), status=200)


@app.route("/job/validate", methods=["POST"])
@cross_origin()
@verify_token()
def validate(user_id):
    #
    request_form = request.form

    #
    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400,
        )

    #
    job_id = str(request_form["job_id"])

    # set all estimation to 0
    db = mongo["RMN"]
    db["job_documents"].update_many(
        {"job_id": job_id},
        {
            "$set": {
                "execution_time": 0,
            }
        },
    )

    # mark job as VALIDATED
    db["eval_jobs"].update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "job_status": Job_Status.VALIDATED.value,
                }
            },
    )

    # add to Redis Queue
    try:
        redis.rpush("job_queue", json.dumps({"job_id": job_id}))
    except Exception as e:
        print(e)
        print("Failed to push job to Redis Queue.")
        return Response(
            response=json.dumps(
                {"response": "Error: Failed to push job to Redis Queue."}
            ),
            status=500,
        )

    return Response(response=json.dumps({"response": "OK"}), status=200)


def delete_job(job_id):
    print("Delete job:", job_id)
    try:
        storage.remove_all_match(job_id)
    except Exception as e:
        print(e)

    #
    db = mongo["RMN"]
    collection = db["job_documents"]
    collection_eval_jobs = db["eval_jobs"]
    collection_output = db["jobs_output"]

    #
    try:
        collection.delete_many({"job_id": job_id})
    except Exception as e:
        print(e)

    #
    try:
        collection_eval_jobs.delete_many({"job_id": job_id})
    except Exception as e:
        print(e)

    try:
        collection_output.delete_many({"job_id": job_id})
    except Exception as e:
        print(e)


@app.route("/job/delete", methods=["POST"])
@cross_origin()
@verify_token()
def delete(user_id):
    request_form = request.form

    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400,
        )

    #
    job_id = str(request_form["job_id"])

    db = mongo["RMN"]
    collection = db["eval_jobs"]
    if collection.count_documents({"user_id": user_id, "job_id": job_id}) == 0:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=400
        )
    delete_job(job_id)

    #
    return Response(response=json.dumps({"response": "OK"}), status=200)


def delete_old_jobs(n_days_old=0, user_id=None):
    db = mongo["RMN"]
    collection = db["eval_jobs"]
    r = {} if user_id is None else {"user_id": user_id}
    jobs = collection.find(r)

    now = dt.datetime.utcnow()  # dt.datetime.now(dt.UTC)
    n = 0
    for j in jobs:
        delta = now - j["queued_time"]
        if delta.days >= n_days_old:
            delete_job(j["job_id"])
            n = n + 1

    return n


@app.route("/admin/delete/jobs", methods=["POST"])
@cross_origin()
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


@app.route("/admin/signup", methods=["POST"])
@cross_origin()
def admin_signup():
    db = mongo["RMN"]
    return UserService.signup(request, db)


@app.route("/admin/delete/tokens", methods=["POST"])
@cross_origin()
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


@app.route("/admin/delete/user", methods=["POST"])
@cross_origin()
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


@app.route("/admin/users", methods=["POST"])
@cross_origin()
def admin_users():
    db = mongo["RMN"]
    all_users = UserService.users(db)
    return Response(response=json.dumps({"response": "OK", "users": all_users}), status=200)


@app.route("/admin/change_password", methods=["POST"])
@cross_origin()
def admin_change_password():
    db = mongo["RMN"]
    return UserService.change_password(request, db, False)


@app.route("/front_page", methods=["POST"])
@cross_origin()
@verify_token()
def front_page(user_id):
    request_form = request.form

    if "suffix" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: suffix not provided."}),
            status=400,
        )

    if not request.files:
        return Response(
            response=json.dumps({"response": "Error: No files provided."}),
            status=400,
        )

    if "moodle_zip" not in request.files:
        return Response(
            response=json.dumps({"response": "Error: moodle_zip file not provided."}),
            status=400,
        )

    if "latex_front_page" not in request.files:
        return Response(
            response=json.dumps(
                {"response": "Error: latex_front_page file not provided."}
            ),
            status=400,
        )


    user_id = str(request_form["user_id"])
    suffix = str(request_form["suffix"])
    moodle_zip = request.files.get("moodle_zip")
    latex_front_page = request.files.get("latex_front_page")

    if not os.path.exists(FRONT_PAGE_TEMP_FOLDER):
        os.makedirs(FRONT_PAGE_TEMP_FOLDER)

    current_temp_folder = FRONT_PAGE_TEMP_FOLDER.joinpath(user_id)

    if not os.path.exists(current_temp_folder):
        os.makedirs(current_temp_folder)

    moodle_zip_name = secure_filename(moodle_zip.filename)
    latex_front_page_name = secure_filename(latex_front_page.filename)

    # Copy latex_input_file in temp_folder
    shutil.copy(LATEX_INPUT_FILE, current_temp_folder)

    moodle_zip_filepath = str(current_temp_folder.joinpath(moodle_zip_name))
    latex_front_page_filepath = str(current_temp_folder.joinpath(latex_front_page_name))
    latex_input_file_filepath = str(current_temp_folder.joinpath("data.tex"))

    with open(moodle_zip_filepath, "wb") as f_out:
        file_content = moodle_zip.stream.read()
        f_out.write(file_content)

    content_temp_folder = current_temp_folder.joinpath("moodle")
    if not os.path.exists(content_temp_folder):
        os.makedirs(content_temp_folder)

    with ZipFile(moodle_zip_filepath, 'r') as zip_ref:
        zip_ref.extractall(content_temp_folder)
    os.remove(moodle_zip_filepath)

    latex_front_page.save(FileIO(latex_front_page_filepath, "wb"))

    handler = FrontPageHandler()
    handler.addFrontPages(
        str(current_temp_folder),
        content_temp_folder,
        suffix,
        latex_front_page_filepath,
        latex_input_file_filepath,
    )

    shutil.make_archive(str(content_temp_folder), "zip", content_temp_folder)

    file_send = send_file(f"{str(content_temp_folder)}.zip")

    shutil.rmtree(str(current_temp_folder))

    return file_send


if __name__ == "__main__":
    app.run(debug=True)
