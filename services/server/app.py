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
from functools import wraps


app = Flask(__name__)
cors = CORS(app)
app.config["CORS_HEADERS"] = "Content-Type"

mongo = mongo_client()
redis = redis_client()
storage = Storage()

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

    if "template_id" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: template_id not provided."}),
            status=400,
        )

    # if "nb_pages" not in request_form:
    #     return Response(
    #         response=json.dumps({"response": f"Error: nb_pages not provided."}),
    #         status=400,
    #     )
    
    if "n_pages_per_question" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: n_pages_per_question not provided."}),
            status=400,
        )

    if "job_name" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: job_name not provided."}),
            status=400,
        )

    if "template_name" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: template_name not provided."}),
            status=400,
        )

    if not request.files:
        return Response(
            response=json.dumps({"response": f"Error: No files provided."}),
            status=400,
        )

    if "notes_csv_file" not in request.files:
        return Response(
            response=json.dumps({"response": f"Error: Notes csv file not provided."}),
            status=400,
        )

    if "zip_file" not in request.files:
        return Response(
            response=json.dumps({"response": f"Error: Zip file not provided."}),
            status=400,
        )

    template_id = str(request_form["template_id"])
    template_name = str(request_form["template_name"])
    job_name = str(request_form["job_name"])
    # nb_pages = int(request_form["nb_pages"])
    n_pages_per_question = json.loads(request_form["n_pages_per_question"])

    # Define db and collection used
    db = mongo["RMN"]
    collection = db["eval_jobs"]

    job_id = str(uuid.uuid4())

    path_on_cloud_zip = "zips/"
    zip_file_id = f"{path_on_cloud_zip}{job_id}.zip"

    path_on_cloud_csv = "csv/"
    notes_file_id = f"{path_on_cloud_csv}{job_id}.csv"

    job = {
        "job_id": job_id,
        "job_name": job_name,
        "user_id": user_id,
        "template_id": template_id,
        "template_name": template_name,
        "queued_time": datetime.utcnow(),
        "job_status": Job_Status.QUEUED.value,
        "retry": 0,
        "notes_file_id": notes_file_id,
        "zip_file_id": zip_file_id,
        "n_pages_per_question": n_pages_per_question,
        "students_list": []
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
        return Response(response=f"Error: Failed to download files.", status=900)

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
            "template_id": job["template_id"],
            "queued_time": str(job["queued_time"]),
            "job_status": job["job_status"],
            "job_name": job["job_name"],
            "template_name": job["template_name"]
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
        "template_id": job["template_id"],
        "queued_time": str(job["queued_time"]),
        "job_status": job["job_status"],
        "job_name": job["job_name"],
        "template_name": job["template_name"],
        "students_list": job["students_list"]
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


@app.route("/file/download", methods=["POST"])
@cross_origin()
@verify_token()
def download_file(user_id):
    #
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


@app.route("/documents", methods=["POST"])
@cross_origin()
@verify_share_token()
def get_documents():
    request_form = request.form
    job_id = str(request_form["job_id"])

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

    if "document_index" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: document_index not provided."}),
            status=400,
        )

    if "matricule" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: matricule not provided."}),
            status=400,
        )

    if "subquestion_predictions" not in request_form:
        return Response(
            response=json.dumps(
                {"response": f"Error: subquestion_predictions not provided."}
            ),
            status=400,
        )

    if "total" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: total not provided."}),
            status=400,
        )

    if "status" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: document_index not provided."}),
            status=400,
        )

    #
    job_id = str(request_form["job_id"])
    document_index = int(request_form["document_index"])
    matricule = str(request_form["matricule"])
    subquestion_predictions = json.loads(request_form["subquestion_predictions"])
    total = float(request_form["total"])

    #
    db = mongo["RMN"]
    collection = db["job_documents"]

    #
    collection.update_one(
        {"job_id": job_id, "document_index": document_index},
        {"$set": {
            "matricule": matricule,
            "subquestion_predictions": subquestion_predictions,
            "total": total,
            "status": Document_Status.VALIDATED.value,
        }
    })

    return Response(response=json.dumps({"response": "OK"}), status=200)


@app.route("/document/download", methods=["POST"])
@cross_origin()
@verify_share_token()
def download_document():
    request_form = request.form

    if "document_index" not in request_form:
        return Response(
            response=json.dumps({"response": f"Error: document_index not provided."}),
            status=400,
        )

    #
    job_id = str(request_form["job_id"])
    document_index = int(request_form["document_index"])

    #
    db = mongo["RMN"]
    document_collection = db["job_documents"]

    #
    document_file = document_collection.find_one({"job_id": job_id, "document_index": document_index})
    if document_file is None:
        return Response(
            response=json.dumps({"response": f"No document found!"}),
            status=404,
        )

    print("document_file: ", document_file)
    # Save file to local
    file_id = str(document_file["image_id"])
    storage.copy_from(file_id, file_id)
    file_send = send_file(file_id)

    time.sleep(0.1)

    @after_this_request
    def add_close_action(response):
        try:
            os.remove(file_id)
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
