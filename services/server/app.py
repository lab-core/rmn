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
from datetime import datetime, timedelta
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
            response=json.dumps({"response": f"Error: token not provided."}),
            status=400,
        ), None
    # check if token valid
    db = mongo["RMN"]
    token = form['token']
    valid, username = UserService.verify_token(token, db, role)
    if not valid:
        return Response(
            response=json.dumps({"response": f"Error: token not valid. Please login."}),
            status=400,
        ), None
    if ("user_id" in form and form["user_id"] != username) or \
            ("username" in form and form["username"] != username):
        print(f"Error: token belongs to username {username}.")
        return Response(
            response=json.dumps({"response": f"Error: token belongs to another username."}),
            status=400,
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


def verify_share_token():
    def _verify_token(f):
        @wraps(f)
        def __verify_token(*args, **kwargs):
            # check if any token share token provided
            if "job_id" not in request.form:
                print("Error: job_id not provided.")
                return Response(
                    response=json.dumps({"response": f"Error: job_id not provided."}),
                    status=400,
                )
            job_id = request.form["job_id"]
            db = mongo["RMN"]

            # check if token valid
            resp, user_id = check_token(request.form)
            if resp is None:
                job = db["eval_jobs"].find_one({"job_id": job_id, "user_id": user_id})
                if job is None:
                    print(f"Error: job {job_id} for user {user_id} doesn't exist.")
                    job = db["eval_jobs"].find_one({"job_id": job_id})
                    if job:
                        print("Found job:", job)
                    return Response(
                        response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
                        status=400
                    )
                return f()
            # check if any token share token provided
            if "share_token" not in request.form:
                return Response(
                    response=json.dumps({"response": f"Error: token not provided."}),
                    status=400,
                )
            # check if share token valid
            db = mongo["RMN"]
            token = request.form["share_token"]
            job = db["eval_jobs"].find_one({"job_id": job_id, "share_token": token})
            if not job:
                print("Error: share token not valid.")
                return Response(
                    response=json.dumps({"response": f"Error: share token not valid."}),
                    status=400,
                )
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
    statistics_for_students = str(request_form["statistics_for_students"])
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
        "queued_time": datetime.utcnow(),
        "job_status": Job_Status.QUEUED.value,
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
            response=json.dumps({"response": f"Error: Failed to insert in MongoDB."}),
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
        return Response(response=f"Error: Failed to download files.", status=500)

    # Create SocketIO connection
    sio = socketio_client()
    sio.emit(
        "jobs_status",
        json.dumps(
            {"job_id": job_id, "status": Job_Status.QUEUED.value, "user_id": user_id}
        ),
    )
    sio.disconnect()

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
            "jobs_status",
            json.dumps(
                {
                    "job_id": job_id,
                    "user_id": user_id,
                    "status": Job_Status.ERROR.value,
                }
            ),
        )
        sio.disconnect()
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
            "regular_template_name": job["regular_template_name"]
        }
        for job in jobs
    ]

    # wake up workers in case some jobs died
    max_alive = datetime.utcnow() - timedelta(seconds=120)

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
            if job["job_status"] == Job_Status.RUN.value:
                requeue(job["job_id"], Job_Status.RUN.value, Job_Status.QUEUED.value)
            else:
                requeue(job["job_id"], Job_Status.FINALIZING.value, Job_Status.VALIDATION.value)

            res = collection.update_one(
                {"job_id": job["job_id"], "job_status": Job_Status.RUN.value},
                {"$inc": {"retry": 1}, "$set": {"job_status": Job_Status.QUEUED.value}}
            )

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
        "job_infos": job["job_infos"],
        "n_max_points_per_question": job["n_max_points_per_question"],
        "copies_informations": job.get("copies_informations", []),
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
            response=json.dumps({"response": f"Error: job_id not provided."}),
            status=400
        )
    job_id = str(request_form["job_id"])

    if "question_index" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: question_index not provided."}),
            status=400
        )
    question_index = int(request_form["question_index"])

    host = request.headers.get('Host')
    if not host:
        return Response(
            response=json.dumps({"response": f"Error: Host is not defined in the headers."}),
            status=400
        )

    # Get all jobs from DB
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
            {"$set": {"share_token": token}})
    else:
        token = job["share_token"]

    if question_index:
        share_url = f"https://{host}/task-validation/?job={job_id}&token={token}&question_index={question_index}"
    else:
        share_url = f"https://{host}/task-validation/?job={job_id}&token={token}"

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
            response=json.dumps({"response": f"Error: job_id not provided."}),
            status=400
        )
    job_id = str(request_form["job_id"])

    # Get all jobs from DB
    res = collection.update_one({"job_id": job_id, "user_id": user_id}, {"$unset": {"share_token": ""}})
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
            response=json.dumps({"response": f"Error: job_id not provided."}),
            status=400,
        )
    
    job_id = str(request_form["job_id"])
    db = mongo["RMN"]
    collection_eval_jobs = db["eval_jobs"]
    collection_eval_jobs.update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "job_status": Job_Status.IGNORED.value,
                }
            },
    )

    collection_documents = db["job_documents"]

    incorrect_files = []
    for key in request_form.keys():
        if key.startswith('incorrect_files'):
            incorrect_files.append(request_form[key])
   
    # delete documents with filenames in incorrect_files
    
    for filename in incorrect_files:
        collection_documents.delete_many({"job_id": job_id, "filename": filename})

    return Response(response=json.dumps({"response": "OK"}), status=200)

@app.route("/job/continue", methods=["POST"])
@cross_origin()
@verify_token()
def continue_job(user_id):

    request_form = request.form
    job_id = str(request_form["job_id"])
    
    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: job_id not provided."}),
            status=400,
        )
    
    if not request.files:
        return Response(
            response=json.dumps({"response": f"Error: No files provided."}),
            status=400,
        )

    # replacing files in output_zip
    pdf_files = [file for key, file in request.files.items() if file.filename.endswith('.pdf')]
    zip_path = storage.abs_path(f"output_zip{os.sep}{job_id}.zip")
    new_zip_path = storage.replace_pdfs_in_zip(zip_path, pdf_files, job_id)
    final_zip_path =  storage.abs_path(f"output_zip{os.sep}")
    shutil.move(new_zip_path, final_zip_path)

    # removing questions pdfs
    questions_folder_path = storage.abs_path(f"documents{os.sep}{job_id}")
    incorrect_files_path = storage.abs_path(f"incorrect_files{os.sep}{job_id}")
    storage.remove_all_files_in_folder(questions_folder_path)
    storage.remove_all_files_in_folder(incorrect_files_path)

    #removing files in database
    db = mongo["RMN"]
    collection = db["job_documents"]
    collection.delete_many({"job_id": job_id})

    # set status to CORRECTED
    db = mongo["RMN"]
    collection_eval_jobs = db["eval_jobs"]
    collection_eval_jobs.update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "job_status": Job_Status.CORRECTED.value,
                }
            },
    )


    return Response(response=json.dumps({"response": "OK"}), status=200)

@app.route("/incorrect/download", methods=["POST"])
@cross_origin()
@verify_token()
def download_incorrect_files(user_id):
    request_form = request.form
    #
    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: job_id not provided."}),
            status=400,
        )

    #
    if "file" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: file not provided."}),
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
            response=json.dumps({"response": f"Error: job_id not provided."}),
            status=400,
        )

    #
    if "file" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: file not provided."}),
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
                {"response": f"Error: invalid value for 'file' param."}
            ),
            status=400,
        )
    if "zip_index" not in request_form and target_file == Output_File.ZIP_FILE:
        return Response(
            response=json.dumps({"response": f"Error: zip_index not provided."}),
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
            response=json.dumps({"response": f"Error: job_id not provided."}),
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
@verify_share_token()
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
    document_index = request_form["document_index"]
    matricule = str(request_form["matricule"])

    # extract the prefix from the document index
    prefix_match = re.match(r'^(.+?)(_Q\d+|_cover)?\.pdf$', os.path.basename(document_index))
    if not prefix_match:
        return Response(
            response=json.dumps({"response": "Error: Invalid document index format."}),
            status=400,
        )
    
    prefix = prefix_match.group(1)

    db = mongo["RMN"]
    collection = db["job_documents"]

    # scan all documents within the job and update the ones that match the prefix
    documents_to_update = collection.find({"job_id": job_id})
    
    for document in documents_to_update:
        document_basename = os.path.basename(document["filename"])
        if document_basename.startswith(prefix):
            update_data = {"matricule": matricule}
            if document_basename.endswith("_cover.pdf"):
                update_data["status"] = Document_Status.VALIDATED.value

            collection.update_one(
                {"_id": document["_id"]},
                {"$set": update_data}
            )

    return Response(response=json.dumps({"response": "OK"}), status=200)

@app.route("/matricule/share", methods=["POST"])
@cross_origin()
@verify_share_token()
def share_matricule_verification():
    # Define db and collection used
    db = mongo["RMN"]
    collection = db["eval_jobs"]

    request_form = request.form
    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: job_id not provided."}),
            status=400
        )
    job_id = str(request_form["job_id"])

    if "user_id" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: user_id not provided."}),
            status=400
        )
    user_id = str(request_form["user_id"])

    host = request.headers.get('Host')
    if not host:
        return Response(
            response=json.dumps({"response": f"Error: Host is not defined in the headers."}),
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
            {"$set": {"share_token": token}})
    else:
        token = job["share_token"]

    share_url = f"https://{host}/matricule-validation/?job={job_id}&token={token}"

    resp = {
        "job_id": job["job_id"],
        "share_url": share_url
    }
    return Response(response=json.dumps({"response": resp}), status=200)

@app.route("/documents", methods=["POST"])
@cross_origin()
@verify_share_token()
def get_documents():
    request_form = request.form
    job_id = str(request_form["job_id"])

    if not job_id:
        return Response(response=json.dumps({"Error": "job_id is missing"}), status=400)

    #
    db = mongo["RMN"]
    collection = db["job_documents"]

    #
    docs = collection.find({"job_id": job_id})
    count = collection.count_documents({"job_id": job_id})

    #
    resp = [
        {
            "job_id": doc["job_id"],
            "document_index": doc["document_index"],
            "subquestion_predictions": doc["subquestion_predictions"],
            "matricule": doc["matricule"],
            "filename": os.path.basename(doc["filename"]),
            "total": doc["total"],
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
@verify_share_token()
def update_document():
    request_form = request.form
    request_files = request.files

    required_fields = ["job_id", "document_index", "copies_informations", "n_max_points_per_question", "status"]
    for field in required_fields:
        if field not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: {field} not provided."}),
                status=400,
            )

    if "file" not in request.files:
        return Response(
            response=json.dumps({"response": "Error: file not provided."}),
            status=400,
        )

    job_id = str(request_form["job_id"])
    document_index = int(request_form["document_index"])
    n_max_points_per_question = json.loads(request_form["n_max_points_per_question"])

    # replacing the previous file by the new one in storage
    file = request_files["file"]
    # file_name = secure_filename(file.filename)
    file_name = file.filename

    last_underscore_index = file_name.rfind('_')
    extension_index = file_name.rfind('.pdf')
    question_index = file_name[last_underscore_index + 1:extension_index]
    
    file_path = os.path.join('documents', job_id, question_index, file_name)
    print("file path ", storage.abs_path(file_path))
    # save with default name as well as the latest version
    abs_filename = storage.abs_path(file_path)
    file.save(abs_filename)
    save_new_version(abs_filename)

    # update the database
    db = mongo["RMN"]
    collection = db["job_documents"]

    collection.update_one(
        {"job_id": job_id, "document_index": document_index},
        {"$set": {
            "n_max_points_per_question": n_max_points_per_question,
            "status": Document_Status.VALIDATED.value,
        }}
    )


    # copies_informations in eval_jobs collection
    copies_informations = json.loads(request_form["copies_informations"])
    collection_eval_jobs = db["eval_jobs"]
    collection_eval_jobs.update_one(
        {"job_id": job_id},
        {"$set": {
            "copies_informations": copies_informations,
        }}
    )

    return Response(response=json.dumps({"response": "OK"}), status=200)

@app.route("/documents/grade_all", methods=["POST"])
@cross_origin()
@verify_share_token()
def grade_all_documents():
    request_form = request.form

    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400,
        )
    
    if "copies_informations" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: copies_informations not provided."}),
            status=400,
        )

    job_id = str(request_form["job_id"])

    db = mongo["RMN"]

    copies_informations = json.loads(request_form["copies_informations"])
    collection_eval_jobs = db["eval_jobs"]
    collection_eval_jobs.update_one(
        {"job_id": job_id},
        {"$set": {
            "copies_informations": copies_informations,
        }}
    )

    return Response(response=json.dumps({"response": "OK"}), status=200)

@app.route("/documents/replace", methods=["POST"])
@cross_origin()
@verify_share_token()
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
                        question_folder = f"Q{question_number.group(1)}"

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
@verify_share_token()
def download_document():
    request_form = request.form

    if "document_index" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: document_index not provided."}),
            status=400,
        )

    job_id = str(request_form["job_id"])
    document_index = request_form["document_index"]

    db = mongo["RMN"]
    document_collection = db["job_documents"]

    if document_index.isdigit():
        document_index = int(document_index)
        document_file = document_collection.find_one({"job_id": job_id, "document_index": document_index})
        if document_file is None:
            return Response(
                response=json.dumps({"response": "No document found!"}),
                status=404,
            )

        file_id = str(document_file["image_id"])
        # add the right version if requested
        if "document_version" in request_form:
            try:
                version_name = version_basename(file_id) + "-%s.pdf" % request_form["document_version"]
                storage.copy_from(version_name, file_id)
            except ValueError:
                # if cannot find this version use default one
                storage.copy_from(file_id, file_id)
        else:
            storage.copy_from(file_id, file_id)
        file_path = file_id
    else:
        document_file = document_collection.find_one({"job_id": job_id, "document_index": document_index})
        if document_file is None:
            return Response(
                response=json.dumps({"response": "No document found!"}),
                status=404,
            )

        file_id = str(document_file["image_id"])
        file_path = os.path.join('cover_pages', job_id, file_id)
        storage.copy_from(file_path, file_path)

    print("document_file: ", document_file)
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

@app.route("/job/validate", methods=["POST"])
@cross_origin()
@verify_token()
def validate(user_id):
    #
    request_form = request.form

    #
    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: job_id not provided."}),
            status=400,
        )

    #
    job_id = str(request_form["job_id"])

    db = mongo["RMN"]
    collection = db["job_documents"]

    # Create SocketIO connection
    sio = socketio_client()
    sio.emit(
        "jobs_status",
        json.dumps(
            {
                "job_id": job_id,
                "status": Job_Status.FINALIZING.value,
                "user_id": user_id,
            }
        ),
    )
    sio.disconnect()

    # add to Redis Queue
    try:
        redis.rpush("job_queue", json.dumps({"job_id": job_id}))
    except Exception as e:
        print(e)
        print("Failed to push job to Redis Queue.")
        return Response(
            response=json.dumps(
                {"response": f"Error: Failed to push job to Redis Queue."}
            ),
            status=500,
        )

    # set all estimation to 0
    collection.update_many(
        {"job_id": job_id},
        {
            "$set": {
                "execution_time": 0,
            }
        },
    )

    return Response(response=json.dumps({"response": "OK"}), status=200)


def delete_job(job_id):
    print("Delete job:", job_id)

    try:
        storage.remove(f"output_csv/{job_id}.csv")
    except Exception as e:
        print(e)
    try:
        storage.remove(f"csv/{job_id}.csv")
    except Exception as e:
        print(e)
    try:
        storage.remove(f"output_zip/{job_id}*.zip")
    except Exception as e:
        print(e)
    try:
        storage.remove(f"zips/{job_id}.zip")
    except Exception as e:
        print(e)
    try:
        storage.remove_tree(f"documents/{job_id}")
    except Exception as e:
        print(e)
    try:
        storage.remove_tree(f"unverified_numbers/{job_id}")
    except Exception as e:
        print(e)
    try:
        storage.remove_tree(f"cover_pages/{job_id}")
    except Exception as e:
        print(e)
    try:
        storage.remove_tree(f"corrected_copies/{job_id}")
    except Exception as e:
        print(e)
    try:
        storage.remove_tree(f"incorrect_files/{job_id}")
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
            response=json.dumps({"response": f"Error: job_id not provided."}),
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

    now = datetime.utcnow()
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
            response=json.dumps({"response": f"Error: n_days_old not provided."}),
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
            response=json.dumps({"response": f"Error: username and user_id not provided. Please one of these two fields."}),
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
            response=json.dumps({"response": f"Error: suffix not provided."}),
            status=400,
        )

    if not request.files:
        return Response(
            response=json.dumps({"response": f"Error: No files provided."}),
            status=400,
        )

    if "moodle_zip" not in request.files:
        return Response(
            response=json.dumps({"response": f"Error: moodle_zip file not provided."}),
            status=400,
        )

    if "latex_front_page" not in request.files:
        return Response(
            response=json.dumps(
                {"response": f"Error: latex_front_page file not provided."}
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
