import glob
import re
from service.template_service import TemplateService
from service.user_service import UserService, Role
from flask import Flask, request, Response, json, send_file
from flask_cors import CORS, cross_origin
from werkzeug.utils import secure_filename
from pathlib import Path
from rmn_common.status import Job_Status, Output_File, Document_Status
from rmn_common import auto_grade
from rmn_common.questions import validate_questions, validate_bonus_map
from rmn_common.moodle import MoodleFields as MF
from utils.storage import Storage
from utils.clients import redis_client, socketio_client, mongo_client
import datetime as dt
from io import FileIO
from service.front_page_service import FrontPageHandler
from service.health_check import start_health_check
from service import storage_cleanup
from threading import Thread
from zipfile import ZipFile
import pandas as pd

import uuid
import os
import hmac
import json
import shutil
import tempfile
from functools import wraps


app = Flask(__name__)


def cors_origins(value):
    """Expand the comma-separated CORS_ORIGINS setting into an allow-list.

    Same syntax as the socketIO service: "*" allows every origin (local
    development), an entry with a scheme is taken as-is and a bare hostname
    allows both https:// and http://, so the deployment can pass the public
    host of rmn-config unchanged.
    """
    if value.strip() == "*":
        return "*"
    origins = []
    for entry in (o.strip() for o in value.split(",")):
        if not entry:
            continue
        if "://" in entry:
            origins.append(entry)
        else:
            origins.extend([f"https://{entry}", f"http://{entry}"])
    return origins


# Which browser origins may call the API. Every route is decorated with
# @cross_origin(), which reads its defaults from these keys: pinned to the
# public host in production (server.yml), "*" when the variable is absent.
app.config["CORS_ORIGINS"] = cors_origins(os.getenv("CORS_ORIGINS", "*"))
app.config["CORS_HEADERS"] = "Content-Type"
cors = CORS(app)

# Cap the request body. The ingress already limits it (proxy-body-size 5G);
# this is the backstop when Flask is reached some other way. Copies zips are
# large, hence the generous default; override with MAX_UPLOAD_GB.
app.config["MAX_CONTENT_LENGTH"] = int(
    float(os.getenv("MAX_UPLOAD_GB", "5")) * 1024**3
)

mongo = mongo_client()
try:
    # TTL index purging expired login tokens (see UserService.TOKEN_TTL_DAYS)
    UserService.ensure_token_expiration(mongo["RMN"])
except Exception as e:  # Mongo unreachable at start-up: verify_token still
    print(f"WARNING: could not create the token TTL index: {e}", flush=True)
    # enforces the TTL on every request, so this is not fatal
redis = redis_client()
sio = socketio_client()
storage = Storage()

# a Redis lock elects one gunicorn worker per tick of the Slack dead-man's
# switch. Dedicated client with short timeouts: the lock must fail open fast
# when Redis is down instead of hanging the tick (and the alert with it).
start_health_check(redis=redis_client(socket_connect_timeout=2, socket_timeout=2))

ROOT_DIR = Path(__file__).resolve().parent
TEMP_FOLDER = ROOT_DIR.joinpath("temp")
VALIDATE_TEMP_FOLDER = ROOT_DIR.joinpath("validate_temp_folder")
FRONT_PAGE_TEMP_FOLDER = ROOT_DIR.joinpath("front_page_temp")
LATEX_INPUT_FILE = ROOT_DIR.joinpath("data.tex")

# Shared operator secret guarding the /admin/* endpoints. These are
# server-side operator commands (create the first admin, reset a password,
# delete a user/jobs, ...) that carry a *target* user in their form fields,
# so they cannot be guarded by the per-user @verify_token. Requiring this
# secret means that merely reaching Flask (e.g. bypassing the nginx deny
# rule) is not enough to call them. Unset => admin endpoints are disabled.
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")


def request_token(form):
    """The login token of the current request.

    Read from ``Authorization: Bearer <token>`` first: a header is not part
    of the multipart body, so it never lands in body logging and the webapp
    sets it in one interceptor instead of in forty forms. The ``token`` form
    (or query) field is still accepted for older clients and share links.
    """
    scheme, _, value = request.headers.get("Authorization", "").strip().partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return form.get("token")


def check_token(form, role=None, check_username=True):
    """The (error response, username) of the token in ``form``.

    ``check_username=False`` for the one route where the form's ``username``
    legitimately names someone else: an admin creating a user on /signup.
    """
    # check if token provided
    token = request_token(form)
    if token is None:
        return Response(
            response=json.dumps({"response": "Error: token not provided."}),
            status=401,
        ), None
    # check if token valid
    db = mongo["RMN"]
    valid, username = UserService.verify_token(token, db, role)
    # "code" lets the webapp tell a dead session (log out, back to the login
    # page) apart from the other 401s (a job or question this user cannot see)
    if not valid:
        return Response(
            response=json.dumps({"response": "Error: token not valid. Please login.", "code": "token_invalid"}),
            status=401,
        ), None
    # both fields, when sent, must name the token's owner. The username check
    # used to be skipped when user_id was also present, so a form with its own
    # user_id and another user's username reached the handlers that update
    # the user named by the form.
    if ("user_id" in form and form["user_id"] != username) or \
            (check_username and "username" in form and form["username"] != username):
        print(f"Error: token belongs to username {username}.")
        return Response(
            response=json.dumps({"response": "Error: token belongs to another username.", "code": "token_invalid"}),
            status=401,
        ), None

    return None, username


def verify_token(role=None, check_username=True):
    def _verify_token(f):
        @wraps(f)
        def __verify_token(*args, **kwargs):
            # check if token valid
            resp, user_id = check_token(request.form, role, check_username)
            if resp:
                return resp
            return f(user_id)
        return __verify_token
    return _verify_token


def verify_admin(f):
    """Guard an /admin/* operator endpoint with the shared ADMIN_API_KEY.

    The secret is read primarily from the ``X-Admin-Key`` request header;
    the ``admin_key`` form/query field is accepted only as a fallback.
    The header is preferred because query-string and form secrets tend to be
    captured in access logs, browser history and Referer headers.
    Fails closed: if ADMIN_API_KEY is not set the endpoint is disabled rather
    than left open.
    """
    @wraps(f)
    def __verify_admin(*args, **kwargs):
        if not ADMIN_API_KEY:
            print("Error: ADMIN_API_KEY is not configured; admin endpoints are disabled.")
            return Response(
                response=json.dumps({"response": "Error: admin endpoints are disabled."}),
                status=403,
            )
        request_form = request.form if request.method == "POST" else request.args
        provided = request.headers.get("X-Admin-Key") or request_form.get("admin_key", "")
        if not hmac.compare_digest(provided.encode("utf-8"), ADMIN_API_KEY.encode("utf-8")):
            return Response(
                response=json.dumps({"response": "Error: invalid admin key."}),
                status=403,
            )
        return f(*args, **kwargs)
    return __verify_admin


def question_allowed(validity, question_index):
    """Whether a share-token scope covers a question.

    ``validity`` is None for the job owner, "questions"/"all" for job-wide
    links and, for a single-question link, the share_token key the client
    asked for ("2", or "Q2" in older links). ``question_index`` is the 1-based
    question number of the document, None when the document has no question.
    Anything else ("mat", garbage) is refused instead of raising.
    """
    if validity is None or validity in ("questions", "all"):
        return True
    if question_index is None:
        return False
    try:
        return int(str(validity).lstrip("Qq")) == int(question_index)
    except (TypeError, ValueError):
        return False


def verify_share_token(question=True, matricule=True, return_validity=False):
    def _verify_token(f):
        @wraps(f)
        def __verify_token(*args, **kwargs):
            if request.method == 'POST':
                request_form = request.form
            else:
                request_form = request.args
            # check if any token share token provided
            if "job_id" not in request_form:
                print("Error: job_id not provided.")
                return Response(
                    response=json.dumps({"response": "Error: job_id not provided."}),
                    status=401,
                )
            job_id = request_form["job_id"]
            db = mongo["RMN"]

            # check if token valid
            resp, user_id = check_token(request_form)
            # if resp is None => valid token
            if resp is None:
                job = db["eval_jobs"].find_one({"job_id": job_id, "user_id": user_id})
                if job is None:
                    print(f"Error: job {job_id} for user {user_id} doesn't exist.")
                    # if there is a share token, try it after
                    if "share_token" not in request_form:
                        return Response(
                            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
                            status=401
                        )
                elif return_validity:
                    return f(None)
                else:
                    return f()

            # check if any token share token provided
            token = request_form.get("share_token", request_form.get("token"))
            if token is None:
                return Response(
                    response=json.dumps({"response": "Error: token not provided."}),
                    status=401,
                )

            # check if share token valid
            db = mongo["RMN"]

            keys = ['all']
            validity = None
            # print(request.path)
            if request.path.startswith('/file/'):
                job = db["jobs_output"].find_one({"job_id": job_id})
                if job and job.get("share_token") == token:
                    validity = 'file'
                else:
                    job = db["eval_jobs"].find_one({"job_id": job_id})
                    if job and job.get("share_token", {}).get("all") == token:
                        validity = 'file'
            else:
                if question:
                    keys.append("questions")
                    if "question_index" in request_form:
                        keys.append(request_form["question_index"])
                if matricule:
                    keys.append("mat")

                job = db["eval_jobs"].find_one({"job_id": job_id})
                if job:
                    for k, t in job.get("share_token", {}).items():
                        if k in keys and t == token:
                            validity = k

                if validity is None:
                    print("Error: share token (", token, ") not valid for", job_id, "and keys", keys)

            if validity is None:
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


@app.after_request
def intercept_response(response: Response):
    # force to close the connection to avoid to hang
    response.headers["Connection"] = "close"
    # Defence in depth: the front nginx adds the full header set (see
    # security_headers), these hold when the API is reached without it.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.errorhandler(413)
def request_too_large(_error):
    return Response(
        response=json.dumps({"response": "Error: request body too large."}),
        status=413,
        mimetype="application/json",
    )


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
@verify_token(Role.ADMIN, check_username=False)  # the form's username is the new user
def signup(user_id):
    db = mongo["RMN"]
    return UserService.signup(request, db)


@app.route("/updateSaveVerifiedImages", methods=["PUT"])
@cross_origin()
@verify_token()
def update_user(user_id):
    db = mongo["RMN"]
    return UserService.update_save_verified_images(user_id, request, db)

@app.route("/updateMoodleStructureInd", methods=["PUT"])
@cross_origin()
@verify_token()
def update_moodle_structure_ind(user_id):
    db = mongo["RMN"]
    return UserService.update_moodle_structure_ind(user_id, request, db)


@app.route("/password", methods=["POST"])
@cross_origin()
@verify_token()
def change_password(user_id):
    db = mongo["RMN"]
    return UserService.change_password(request, db, True, username=user_id)


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
    try:
        n_pages_per_question = json.loads(request_form["n_pages_per_question"])
        n_max_points_per_question = json.loads(request_form["n_max_points_per_question"])
        bonus_enabled_map = json.loads(request_form["bonus_enabled_map"])
    except ValueError:
        return Response(
            response=json.dumps({"response": "Error: format des questions invalide."}),
            status=400,
        )
    # a question with 0 page and 0 point is ignored: the executor skips it but
    # keeps its position so the grades match the boxes of the template
    error = validate_questions(n_pages_per_question, n_max_points_per_question, bonus_enabled_map)
    if error:
        return Response(
            response=json.dumps({"response": f"Error: {error}"}),
            status=400,
        )

    db = mongo["RMN"]
    collection = db["eval_jobs"]

    job_id = str(uuid.uuid4())

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
        "queued_time": dt.datetime.now(dt.UTC),
        "job_status": Job_Status.SPLIT.value,
        "retry": 0,
        "notes_file_id": notes_file_id,
        "n_pages_per_question": n_pages_per_question,
        "n_max_points_per_question": n_max_points_per_question,
        "bonus_enabled_map": bonus_enabled_map,
        "students_list": [],
        "statistics_for_students": statistics_for_students,
        "validate_matricule": request_form.get("validate_matricule", "true").lower() == "true",
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
        notes_csv_file_name = temp_upload_path(notes_csv_file.filename)
        notes_csv_file.save(FileIO(notes_csv_file_name, "wb"))
        save_csv(str(notes_csv_file_name), notes_file_id)

        zip_file = request.files.get("zip_file")
        random_id = uuid.uuid4()
        zip_file_id = os.path.join("zips", job_id, f"{random_id}.zip")
        # Stream straight into the storage share, in chunks. The previous code
        # read the whole upload into memory (a multi-GB zip in one gunicorn
        # worker, fatal under the container memory limit) and then copied it a
        # second time from the temp folder to the share, which for 5 GB took
        # longer than the gunicorn worker timeout.
        zip_abs_path = storage.abs_path(zip_file_id)
        os.makedirs(os.path.dirname(zip_abs_path), exist_ok=True)
        zip_file.save(zip_abs_path)
    except Exception as e:
        print(e)
        # no orphan: a SPLIT job without files would sit in the history forever
        collection.delete_one({"job_id": job_id})
        return Response(response="Error: Failed to download files.", status=500)

    # add to Redis Queue
    redis.rpush("job_queue", json.dumps({"job_id": job["job_id"]}))

    # Create SocketIO connection
    sio.emit(
        "job_status",
        json.dumps(
            {"job_id": job_id, "status": Job_Status.SPLIT.value, "user_id": user_id}
        ),
    )

    return Response(response=json.dumps({"response": "OK"}), status=200)


def temp_upload_path(filename):
    """A path under TEMP_FOLDER that no other request can be using.

    The client filename alone collided: two users uploading ``notes.csv`` in
    the same second overwrote each other's temp file, so one job got the
    other's roster.
    """
    os.makedirs(TEMP_FOLDER, exist_ok=True)
    return TEMP_FOLDER.joinpath(f"{uuid.uuid4()}_{secure_filename(filename or '') or 'upload'}")


def save_csv(file_name, notes_file_id):
    # Check if separated by ; or , -> and transform to real csv (,) if needed
    df_comma = pd.read_csv(file_name, nrows=1, sep=",")
    df_semi = pd.read_csv(file_name, nrows=1, sep=";")
    if df_semi.shape[1] > df_comma.shape[1]:
        df_semi = pd.read_csv(file_name, sep=";")
        df_semi.to_csv(file_name)  # save with a ',' separator
    return storage.move_to(file_name, notes_file_id)


@app.route("/template", methods=["POST"])
@cross_origin()
@verify_token()
def create_template(user_id):
    db = mongo["RMN"]
    return TemplateService.create_user_template(request, db, storage)


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
    return TemplateService.delete_template(user_id, request, db, storage)


@app.route("/template/info", methods=["POST"])
@cross_origin()
@verify_token()
def get_template_info(user_id):
    db = mongo["RMN"]
    return TemplateService.get_template_info(user_id, request, db)


@app.route("/template/download", methods=["POST"])
@cross_origin()
@verify_token()
def download_template(user_id):
    db = mongo["RMN"]
    return TemplateService.download_template_file(user_id, request, db, storage)

@app.route("/template/download/src", methods=["post"])
@cross_origin()
@verify_token()
def download_template_source(user_id):
    db = mongo["RMN"]
    return TemplateService.download_template_source(user_id, request, db)


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
            "front_template_id": job.get("front_template_id"),
            "regular_template_id": job.get("regular_template_id"),
            "queued_time": str(job["queued_time"]),
            "job_status": job["job_status"],
            "job_name": job["job_name"],
            "front_template_name": job.get("front_template_name"),
            "regular_template_name": job.get("regular_template_name"),
            "job_infos": job.get("job_infos", ""),
            # so the task list can say a reading is under way
            "auto_grade_running": auto_grade.is_running(
                db["job_questions"], job["job_id"]
            ),
        }
        for job in jobs
    ]

    # wake up workers in case some jobs died
    max_alive = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=120)

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
        if job["job_status"] == Job_Status.RUN.value and job["alive_time"].replace(tzinfo=dt.UTC) < max_alive:
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
        "front_template_id": job.get("front_template_id"),
        "regular_template_id": job.get("regular_template_id"),
        "queued_time": str(job["queued_time"]),
        "job_status": job["job_status"],
        "job_name": job["job_name"],
        "front_template_name": job.get("front_template_name"),
        "regular_template_name": job.get("regular_template_name"),
        "students_list": job["students_list"],
        "job_infos": job.get("job_infos", ""),
        "n_max_points_per_question": job["n_max_points_per_question"],
        "n_pages_per_question": job["n_pages_per_question"],
        "bonus_enabled_map": job["bonus_enabled_map"],
        "statistics_for_students": job["statistics_for_students"],
        "groups": job.get("groups", [""]),
        "copies_errors": job.get("copies_errors"),
        # how far the grade reading has got, question by question, so the
        # dashboard and the correction screen can say what is waiting on what
        "auto_grade_progress": auto_grade.progress(db["job_questions"], job_id),
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
    question_index = request_form.get("question_index")
    all = request_form.get("all")

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
            status=404
        )

    key = "all" if all else question_index if question_index else "questions"
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
    elif all:
        share_url = f"{proto}://{host}/dashboard/?job_id={job_id}&token={token}"
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
    if request_form.get("all"):
        key = "all"
    else:
        key = request_form.get("question_index", "questions")
    res = collection.update_one({"job_id": job_id, "user_id": user_id}, {"$unset": {f"share_token.{key}": ""}})
    if res.matched_count == 0:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=404
        )

    return Response(response=json.dumps({"response": "OK"}), status=200)


@app.route("/job/update/bonus", methods=["POST"])
@cross_origin()
@verify_token()
def bonus_job(user_id):
    request_form = request.form
    #
    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400,
        )

    if "bonus_enabled_map" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: statistics_for_students not provided."}),
            status=400,
        )

    job_id = str(request_form["job_id"])
    try:
        bonus_enabled_map = json.loads(request_form["bonus_enabled_map"])
    except ValueError:
        return Response(response=json.dumps({"response": "Error: bonus_enabled_map is not JSON."}), status=400)
    # the executor reads this list back: malformed input used to be stored as is
    error = validate_bonus_map(bonus_enabled_map)
    if error:
        return Response(response=json.dumps({"response": f"Error: {error}"}), status=400)
    db = mongo["RMN"]
    # scope to the requesting user so one user cannot mutate another's job
    result = db["eval_jobs"].update_one(
            {"job_id": job_id, "user_id": user_id},
            {
                "$set": {"bonus_enabled_map": bonus_enabled_map},
            },
    )
    if result.matched_count == 0:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=404,
        )

    return Response(response=json.dumps({"response": "OK"}), status=200)


@app.route("/job/update/stats", methods=["POST"])
@cross_origin()
@verify_token()
def stats_job(user_id):
    request_form = request.form
    #
    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400,
        )

    if "statistics_for_students" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: statistics_for_students not provided."}),
            status=400,
        )

    job_id = str(request_form["job_id"])
    statistics_for_students = request_form["statistics_for_students"].lower() == "true"
    db = mongo["RMN"]
    # scope to the requesting user so one user cannot mutate another's job
    result = db["eval_jobs"].update_one(
            {"job_id": job_id, "user_id": user_id},
            {
                "$set": {"statistics_for_students": statistics_for_students},
            },
    )
    if result.matched_count == 0:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=404,
        )

    return Response(response=json.dumps({"response": "OK"}), status=200)


@app.route("/job/update/csv", methods=["POST"])
@cross_origin()
@verify_token()
def csv_job(user_id):
    request_form = request.form

    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400,
        )
    job_id = str(request_form["job_id"])

    if "csv" not in request.files:
        return Response(
            response=json.dumps({"response": "Error: csv file not provided."}),
            status=400,
        )

    # scope to the requesting user (before any file work) so one user cannot
    # overwrite another's job csv
    if mongo["RMN"]["eval_jobs"].find_one({"job_id": job_id, "user_id": user_id}) is None:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=404,
        )

    # save csv locally
    if not os.path.exists(TEMP_FOLDER):
        os.makedirs(TEMP_FOLDER)
    notes_csv_file = request.files.get("csv")
    notes_csv_file_name = str(temp_upload_path(notes_csv_file.filename))
    notes_csv_file.save(FileIO(notes_csv_file_name, "wb"))

    # replace old csv file
    notes_file_id = f"output_csv{os.sep}{job_id}.csv"
    grades_csv_file = save_csv(notes_csv_file_name, notes_file_id)

    # update students list
    grades_df = pd.read_csv(grades_csv_file)
    names_mat_df = grades_df.reset_index()[[MF.mat, MF.name]]
    names_mat_df = names_mat_df.rename(columns={MF.mat: "matricule"})
    students_list = names_mat_df.to_dict(orient="records")
    mongo["RMN"]["eval_jobs"].update_one(
        {"job_id": job_id},
        {"$set": { "students_list": students_list }
    })

    return Response(response=json.dumps({"response": "OK"}), status=200)


@app.route("/job/update/status", methods=["POST"])
@cross_origin()
@verify_token()
def status_job(user_id):
    request_form = request.form
    #
    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400,
        )

    if "job_status" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_status not provided."}),
            status=400,
        )



    job_id = str(request_form["job_id"])
    try:
        status = Job_Status(request_form["job_status"].upper())
    except:
        return Response(
            response=json.dumps({"response": "Error: job_status not recognized."}),
            status=400,
        )

    db = mongo["RMN"]
    # scope to the requesting user so one user cannot mutate another's job
    result = db["eval_jobs"].update_one(
            {"job_id": job_id, "user_id": user_id},
            {
                "$set": {"job_status": status.value},
            },
    )
    if result.matched_count == 0:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=404,
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

    # fetch current job, scoped to the requesting user (returns None -> 404 for
    # a missing or foreign job, which also avoids dereferencing None below)
    job_id = str(request_form["job_id"])
    db = mongo["RMN"]
    collection_eval_jobs = db["eval_jobs"]
    job = collection_eval_jobs.find_one({"job_id": job_id, "user_id": user_id})

    if job is None:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=404,
        )

    # set new status and remove job infos message
    query = {"$unset": {"copies_errors": "", "job_infos": ""}}
    if job["job_status"] == Job_Status.RETRY.value:
        query["$set"] = {"job_status": Job_Status.IGNORED.value}
    db["eval_jobs"].update_one({"job_id": job_id}, query)

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
    # scope the lookup to the requesting user so a user cannot add copies to
    # another user's job (returns None -> 404 for a missing or foreign job_id,
    # which also avoids dereferencing None below).
    job = collection_eval_jobs.find_one({"job_id": job_id, "user_id": user_id})

    if job is None:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=404,
        )

    avail_status = [Job_Status.RETRY.value, Job_Status.QUEUED.value, Job_Status.RUN.value, Job_Status.VALIDATION.value]
    if job["job_status"] not in avail_status:
        return Response(
            response=json.dumps({"response": f"Error: job status is not in {avail_status}."}),
            status=404,
        )

    random_id = uuid.uuid4()
    zip_path = storage.abs_path(os.path.join("zips", job_id, f"{random_id}.zip"))
    # zips/<job_id>/ normally exists since /evaluate created it; do not depend on it
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    # Sanitize the client-supplied filename: it becomes the archive member name,
    # and "../../etc/cron.d/x" must not escape the zip root when extracted.
    # Each upload is copied once, straight from the request into the archive
    # (no temp file), so a multi-GB copies zip is not written twice.
    # force_zip64: the member size is unknown up front and may exceed 2 GiB.
    with ZipFile(zip_path, 'w') as new_zip:
        for f in request.files.values():
            safe_name = secure_filename(f.filename) or f"{uuid.uuid4()}.pdf"
            with new_zip.open(safe_name, 'w', force_zip64=True) as member:
                shutil.copyfileobj(f.stream, member, 8 * 1024 * 1024)

    # removing incorrect pdfs
    storage.remove_tree(os.path.join("incorrect_files", job_id))

    # set new status and remove job infos message
    query = {"$unset": {"copies_errors": "", "job_infos": ""}}
    if job["job_status"] == Job_Status.RETRY.value:
        query["$set"] = {"job_status": Job_Status.CORRECTED.value}

    collection_eval_jobs.update_one({"job_id": job_id}, query)

    # add to Redis Queue
    redis.rpush("job_queue", json.dumps({"job_id": job_id, "add_copies": True}))

    return Response(response=json.dumps({"response": "OK"}), status=200)


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

    # scope to the requesting user so one user cannot read another's files
    if mongo["RMN"]["eval_jobs"].find_one({"job_id": job_id, "user_id": user_id}) is None:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=404,
        )

    # sanitize the client-supplied name to prevent path traversal: without this
    # "file=../../../../etc/passwd" would be served. Incorrect files are stored
    # under flat secure_filename names (see executor utils/split.py), so this is
    # idempotent for legitimate names.
    target_file = secure_filename(str(request_form["file"]))
    if not target_file:
        return Response(
            response=json.dumps({"response": "Error: invalid file name."}),
            status=400,
        )

    file_path = storage.abs_path(os.path.join('incorrect_files', job_id, target_file))
    if not os.path.isfile(file_path):
        return Response(
            response=json.dumps({"response": f"Error: file {target_file} not found."}),
            status=404,
        )

    return send_file(file_path)


@app.route("/file/share", methods=["POST"])
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

@app.route("/file/unshare", methods=["POST"])
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


@app.route("/file/download", methods=["GET", "POST"])
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


@app.route("/job/batch/info", methods=["POST"])
@cross_origin()
@verify_share_token(question=False, matricule=False)  # just token all
def get_info_zip():
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
    collection = db["eval_jobs"]
    output_collection = db["jobs_output"]

    #
    job = collection.find_one({"job_id": job_id})
    stats = job["statistics_for_students"]

    #
    output_files = output_collection.find_one({"job_id": job_id})
    if not output_files:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} doesn't exist."}),
            status=404
        )
    #
    nZips = len(output_files["zip_id_list"])

    #
    return Response(response=json.dumps({"nZips": nZips, "stats": stats}), status=200)


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


@app.route("/matricule/status/update", methods=["POST"])
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
    document_index = int(request_form["document_index"])
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


@app.route("/matricule/unshare", methods=["POST"])
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


@app.route("/documents", methods=["POST"])
@cross_origin()
@verify_share_token(return_validity=True)
def get_documents(validity):
    request_form = request.form
    job_id = str(request_form["job_id"])

    if not job_id:
        return Response(response=json.dumps({"Error": "job_id not provided"}), status=400)

    #
    db = mongo["RMN"]
    query = {"job_id": job_id}
    if request_form.get("documents_indices"):
        query["document_index"] = {"$in": json.loads(request_form["documents_indices"])}

    if request_form.get("questions") is not None:
        if validity == "mat":
            return Response(response=json.dumps({"Error": "You don't have access to these questions"}), status=401)
        question = None
        if validity is not None and validity != "questions" and validity != "all":
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
                "tag": doc.get("tag"),
                "n_total_doc": count,
                # what the reader made of the page, for the correction screen
                # to offer; absent on documents older than the feature
                **auto_grade.projection(doc),
            }
            for doc in docs if question is None or doc["question"] == question
        ]
        resp = sorted(resp, key=lambda k: k["document_index"])
        if resp and resp[-1]["document_index"] - resp[0]["document_index"] != len(resp) - 1:
            print(resp)
            print(resp[-1]["document_index"], "-", resp[0]["document_index"], " != ", len(resp) - 1)
            return Response(response=json.dumps({"Error": "The indices are not consecutive and increasing"}), status=400)
    else:
        if validity is not None and validity != "mat" and validity != "all":
            return Response(response=json.dumps({"Error": "You don't have access to these documents"}), status=401)
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
@verify_share_token(matricule=False, return_validity=True)
def replace_document(validity):
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
    grades = json.loads(request_form["grades"]) if "grades" in request_form else {}

    file = request_files["file"]
    temp_file = tempfile.NamedTemporaryFile(delete_on_close=False)
    # streamed: the upload used to be read whole into memory first
    file.save(temp_file)
    temp_file.flush()

    # A supplied grade wins for the copy it covers -- start_run only queues
    # documents that have none -- but one grade in the map used to call off the
    # reading for the whole upload, silently.
    read_grades = request_form.get("read_grades", "true").lower() == "true"

    # before the thread: it is the one that drops them, and its answer has
    # already gone by the time it does
    skipped = skipped_questions(validity, job_id, temp_file.name, grades)

    thread = Thread(target=replace_thread,
                    args=[validity, job_id, grades, temp_file, read_grades])
    thread.start()

    return Response(
        response=json.dumps({"response": "OK", "skipped_questions": skipped}),
        status=200,
    )


def skipped_questions(validity, job_id, zip_path, grades):
    """The questions of an upload this caller may not modify.

    The pdfs and the csv rows of a question outside the caller's scope are
    dropped, one by one, deep inside a thread whose answer has already been
    sent -- so the upload looked like it had worked in full. This is read
    before the thread starts, so the answer can name what will not be
    written.

    Args:
        validity: The share-token scope, None for the job owner.
        job_id: The job the upload belongs to.
        zip_path: The uploaded archive; a broken one names no question here
            and fails in the thread as it did before.
        grades: The csv grades, keyed by document index.

    Returns:
        The refused questions, as the labels the teacher sees ("Q2"), sorted.
    """
    questions = set()
    try:
        with ZipFile(zip_path, "r") as zip_file:
            for name in zip_file.namelist():
                found = re.search(r"Q(\d+)(?=\.pdf$)", name)
                if found:
                    questions.add(int(found.group(1)))
    except Exception as e:
        print(f"{job_id}: cannot list the uploaded zip ({e})")
    if grades:
        # the csv covers copies, which carry their own question
        questions.update(mongo["RMN"]["job_questions"].distinct(
            "question_index",
            {"job_id": job_id,
             "document_index": {"$in": [int(i) for i in grades]}},
        ))
    # a copy with no question (a whole-copy upload) has nothing to name
    refused = [
        q for q in questions
        if q is not None and not question_allowed(validity, q)
    ]
    return [f"Q{q}" for q in sorted(refused)]


def replace_thread(validity, job_id, grades, temp_file, read_grades=False):
    # the temp file is removed whatever happens: an exception in the detached
    # thread used to leak it (the 200 has already been sent)
    try:
        replace_documents(validity, job_id, grades, temp_file.name, read_grades)
    finally:
        temp_file.close()
        if os.path.exists(temp_file.name):
            os.remove(temp_file.name)


def replace_documents(validity, job_id, grades, zip_path, read_grades=False):
    # read_grades has to be a parameter: without one the name resolved to the
    # /job/read_grades view function, which is always truthy, so the flag was
    # never actually read and no test could tell
    db = mongo["RMN"]

    for doc_index, grade in grades.items():
        doc_index = int(doc_index)
        q_doc = db["job_questions"].find_one({"job_id": job_id, "document_index": doc_index})
        if q_doc is None:
            print('Invalid document_index:', job_id, doc_index)
            continue

        # scope before the write: the status and grade used to be updated
        # first and only the job_documents mirror skipped
        if not question_allowed(validity, q_doc["question_index"]):
            print("You don't have access to question", q_doc["question_index"])
            continue

        db["job_questions"].update_one(
            {"job_id": job_id, "document_index": doc_index},
            {"$set": {
                "status": Document_Status.VALIDATED.value,
                "grade": grade
            }}
        )

        q_index = int(q_doc["question_index"]) - 1
        r = db["job_documents"].update_one(
            {"job_id": job_id, "filename": q_doc["basename"]},
            {"$set": {
                f"grades.{q_index}": grade
            }}
        )
        if not r:
            print('Invalid filename:', job_id, q_doc["basename"])

    touched_questions = set()
    with ZipFile(zip_path, 'r') as zip_file:
        for file_info in zip_file.infolist():
            if not file_info.filename.endswith(".pdf"):
                continue

            extracted_path = zip_file.extract(file_info, path=TEMP_FOLDER)
            # extracting question number from the filename
            question_number = re.search(r'Q\d+(?=\.pdf$)', file_info.filename)
            if question_number:
                question_folder = question_number.group(0)
                # validity = None => logged user
                if not question_allowed(validity, question_folder[1:]):
                    print("You don't have access to question", question_folder)
                    continue

                storage_path = os.path.join('documents', job_id, question_folder, os.path.basename(file_info.filename))
                final_destination = storage.abs_path(storage_path)

                if not os.path.exists(os.path.dirname(final_destination)):
                    os.makedirs(os.path.dirname(final_destination), exist_ok=True)

                # moving the extracted file to the final destination
                shutil.move(extracted_path, final_destination)
                # save new version
                version_filepath = save_new_pdf_version(final_destination)
                last_version = get_last_version(job_id, storage_path)
                db["versions"].insert_one(
                    {"job_id": job_id, "rel_filepath": storage_path, "version": last_version + 1,
                     "version_filepath": version_filepath, "annotations": []}
                )
                touched_questions.add(int(question_folder[1:]))

    if read_grades and touched_questions:
        start_reading_grades(job_id, sorted(touched_questions))
    elif read_grades:
        print(f"{job_id}: nothing to read, the upload carried no question pdf")


def start_reading_grades(job_id, question_indices):
    """Queue a reading pass per question whose pages were just replaced.

    One payload per question, because that is the unit of work: two questions
    uploaded separately are read at the same time by the two executor pods.
    The run number is what lets a second upload of the same question overtake
    the first -- the executor re-checks it and abandons a pass that is no
    longer current.

    This runs after the files are in the storage tree: an executor pod picking
    the job up earlier would read whatever was there before.
    """
    db = mongo["RMN"]
    for question_index in question_indices:
        try:
            run = auto_grade.start_run(
                db["eval_jobs"], db["job_questions"], job_id, question_index
            )
            redis.rpush("job_queue", json.dumps({
                "job_id": job_id,
                "read_grades": True,
                "question_index": question_index,
                "run": run,
            }))
        except Exception as e:
            print(f"Could not queue the grade reading of Q{question_index}: {e}")


def version_basename(filename):
    version_dir = os.path.join(os.path.dirname(filename), "versions")
    version_name = os.path.basename(filename).rsplit(".", 1)[0]
    return os.path.join(version_dir, version_name)


def save_new_pdf_version(filename):
    version_base = version_basename(filename)
    # the split step makes this directory, but a copy that arrives without one
    # used to fail inside the upload thread, after the 200 had been sent: the
    # teacher saw a successful upload and the file was gone
    os.makedirs(os.path.dirname(version_base), exist_ok=True)
    all_versions = glob.glob(version_base+"-*.pdf")
    n_version = len(all_versions)

    # create backup of the file
    version_filepath = version_base + "-%d.pdf" % n_version
    print(f"Save new pdf version ({n_version}):", version_filepath)
    shutil.copy(filename, version_filepath)
    return version_filepath


@app.route("/job/read_grades", methods=["POST"])
@cross_origin()
@verify_share_token(matricule=False, return_validity=True)
def read_grades(validity):
    """Re-read the grades written on a job's pages, without re-uploading.

    How a teacher retries after fixing a copy, and how the reader is exercised
    on a real job without going through an export/import cycle. Questions a
    share link does not cover are skipped, and documents someone has already
    validated are never re-read.

    Form fields: ``job_id``, and ``question_index`` to limit the pass to one
    question (default: every question of the job).
    """
    request_form = request.form
    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400,
        )

    # verify_share_token has already refused a job this caller cannot see
    job_id = str(request_form["job_id"])
    db = mongo["RMN"]

    if "question_index" in request_form:
        try:
            questions = [int(request_form["question_index"])]
        except ValueError:
            return Response(
                response=json.dumps(
                    {"response": "Error: question_index is not a number."}
                ),
                status=400,
            )
    else:
        questions = sorted(db["job_questions"].distinct(
            "question_index", {"job_id": job_id}
        ))

    allowed = [q for q in questions if question_allowed(validity, q)]
    if not allowed:
        return Response(
            response=json.dumps({"response": "Error: no question to read."}),
            status=401,
        )

    start_reading_grades(job_id, allowed)
    return Response(
        response=json.dumps({"response": "OK", "questions": allowed}), status=200
    )


@app.route("/document/tag", methods=["POST"])
@cross_origin()
@verify_share_token(matricule=False, return_validity=True)
def tag_document(validity):
    request_form = request.form
    required_fields = ["job_id", "document_index", "tag"]
    for field in required_fields:
        if field not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: {field} not provided."}),
                status=400,
            )

    db = mongo["RMN"]
    query = {"job_id": str(request_form["job_id"]), "document_index": int(request_form["document_index"])}
    q_doc = db["job_questions"].find_one(query)
    if q_doc is None:
        return Response(response=json.dumps({"response": "Error: document not found."}), status=404)
    # a single-question link may only tag its own question
    if not question_allowed(validity, q_doc.get("question_index")):
        return Response(response=json.dumps({"Error": "You don't have access to this document"}), status=401)
    db["job_questions"].update_one(query, {"$set": {"tag": request_form["tag"]}})

    return Response(response=json.dumps({"response": "OK"}), status=200)

@app.route("/document/update", methods=["POST"])
@cross_origin()
@verify_share_token(matricule=False, return_validity=True)
def update_document(validity):
    request_form = request.form
    required_fields = ["job_id", "document_index", "status"]
    for field in required_fields:
        if field not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: {field} not provided."}),
                status=400,
            )

    version = None
    annotations = []
    if "annotations" in request_form and request_form["annotations"] is not None:
        if "version" not in request_form:
            return Response(
                response=json.dumps({"response": f"Error: field version not provided with annotations."}),
                status=400,
            )
        version = int(request_form["version"])
        annotations = json.loads(request_form.get("annotations"))

    try:
        status = request_form["status"].upper()
        doc_status = Document_Status(status)
    except:
        return Response(
            response=json.dumps({"response": "Error: document status not recognized."}),
            status=400,
        )

    job_id = str(request_form["job_id"])
    document_index = int(request_form["document_index"])

    # update the database
    db = mongo["RMN"]

    # Share-token scope comes first, before any write. It used to be checked
    # only inside the grades branch, after the question had been updated, so
    # a file upload named after another question went through on a
    # single-question link.
    q_doc = db["job_questions"].find_one({"job_id": job_id, "document_index": document_index})
    if not question_allowed(validity, q_doc["question_index"] if q_doc else None):
        return Response(response=json.dumps({"Error": "You don't have access to this document"}), status=401)

    # first update question and job if any
    if "grades" in request_form or "tag" in request_form:
        if "question_index" in request_form:
            set_query = {
                "status": doc_status.value,
            }
            grade = None
            if request_form.get("grades") is not None:
                grade = float(request_form["grades"])
                set_query['grade'] = grade
            if request_form.get("tag") is not None:
                set_query['tag'] = request_form.get("tag")
            q_doc = db["job_questions"].find_one_and_update(
                {"job_id": job_id, "document_index": document_index},
                {"$set": set_query}
            )
            if q_doc is None:
                return Response(response=json.dumps({"response": f"Error: question {document_index} not found."}),
                                status=404)

            if grade is not None:
                q_index = int(request_form["question_index"]) - 1
                r = db["job_documents"].update_one(
                    {"job_id": job_id, "filename": q_doc["basename"]},
                    {"$set": {
                        f"grades.{q_index}": grade
                    }}
                )
                if not r:
                    return Response(response=json.dumps({"response": "Error: document %s not found." % q_doc["basename"]}),
                                    status=404)

                # The teacher has just told us what this page was really
                # worth. Questions of one exam are graded by different people,
                # each writing the grade their own way, so when a question's
                # readings keep disagreeing with the human, the reader has the
                # wrong idea of that question. The readings stay -- the right
                # answer is still usually among them -- but the copies stop
                # being shown as confident.
                question_index = int(request_form["question_index"])
                if auto_grade.unreliable(db["job_questions"], job_id, question_index):
                    distrusted = auto_grade.distrust_suggestions(
                        db["job_questions"], job_id, question_index
                    )
                    if distrusted:
                        print(f"Q{question_index} of {job_id}: readings disagreed "
                              f"with the teacher too often, {distrusted} no longer "
                              "shown as confident")
        else:
            # the grades of every question of the copy, as a JSON list. This
            # branch iterated the JSON text character by character and then
            # returned 404 unconditionally.
            try:
                grades = [float(g) for g in json.loads(request_form["grades"])]
            except (TypeError, ValueError):
                return Response(response=json.dumps({"response": "Error: grades must be a JSON list of numbers."}),
                                status=400)
            r = db["job_documents"].update_one(
                {"job_id": job_id, "document_index": document_index},
                {"$set": {
                    "status": doc_status.value,
                    "grades": grades
                }}
            )
            if r.matched_count == 0:
                return Response(response=json.dumps({"response": f"Error: document {document_index} not found."}),
                                status=404)

    # replacing the previous file by the new one in storage if any
    if "file" in request.files:
        file = request.files["file"]
        file_name = secure_filename(file.filename)

        last_underscore_index = file_name.rfind('_')
        extension_index = file_name.rfind('.pdf')
        question = file_name[last_underscore_index + 1:extension_index]
        # the folder comes from the client filename: keep it to the layout the
        # executor creates (Q<n> or all) and to the question this link covers
        if not re.fullmatch(r"Q\d+|all", question):
            return Response(response=json.dumps({"response": "Error: unexpected filename."}), status=400)
        if not question_allowed(validity, question[1:] if question != "all" else None):
            return Response(response=json.dumps({"Error": "You don't have access to this document"}), status=401)

        # get default name
        rel_filepath = os.path.join('documents', job_id, question, file_name)
        abs_filepath = storage.abs_path(rel_filepath)

        # get last version
        last_version = get_last_version(job_id, rel_filepath)

        # set version to last version by default
        if version is None or version > last_version:
            version = last_version

        # if document has been restored, use a new version from the last available pdf
        if version == -1:
            # save the last available pdf as a new version
            version_filepath = save_new_pdf_version(abs_filepath)
            version = last_version
        # fetch doc version
        else:
            version_doc = db["versions"].find_one({"job_id": job_id, "rel_filepath": rel_filepath, "version": version})
            version_filepath = version_doc["version_filepath"]

        # save this pdf with default name -> become latest available pdf
        file.save(abs_filepath)

        # save new version
        db["versions"].insert_one(
            {"job_id": job_id, "rel_filepath": rel_filepath, "version": last_version + 1,
             "version_filepath": version_filepath, "annotations": annotations}
        )

        print(f"Saved new version ({last_version + 1}) for",
              {"job_id": job_id, "rel_filepath": rel_filepath,
              "version_filepath": version_filepath, "version": version},
              "with %d annotation layers" % len(annotations))

    # The teacher annotated the copy in the app and saved it without typing a
    # grade: the mark they drew is on the page now, so read it. Only this copy
    # is queued -- a save is one copy, not a question. The form is read
    # directly because `grade` above is only bound when the request carried
    # grades or a tag.
    # the form is read directly: `grade` above is only bound when the request
    # carried grades or a tag, and a name that may not exist in this scope is
    # exactly what hid the last of these bugs
    if (
        "file" in request.files
        and not request_form.get("grades")
        and "question_index" in request_form
        and doc_status != Document_Status.VALIDATED
    ):
        queued_run = auto_grade.queue_document(
            db["eval_jobs"], db["job_questions"], job_id,
            int(request_form["question_index"]), document_index,
        )
        if queued_run:
            redis.rpush("job_queue", json.dumps({
                "job_id": job_id,
                "read_grades": True,
                "question_index": int(request_form["question_index"]),
                "run": queued_run,
            }))

    user_id = db["eval_jobs"].find_one({"job_id": job_id})["user_id"]

    sio.emit(
        "doc_validated",
        json.dumps(
            {"job_id": job_id, "user_id": user_id, "document_index": document_index, "questions": True}
        ),
    )

    return Response(response=json.dumps({"response": "OK"}), status=200)


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
            return Response(response=json.dumps({"Error": "You don't have access to this question"}), status=401)

        question_collection = db["job_questions"]
        doc = question_collection.find_one({"job_id": job_id, "document_index": document_index})
        if doc is None:
            return Response(
                response=json.dumps({"response": "No document found!"}),
                status=404,
            )

        if (validity is not None and validity != "questions" and
                validity != "all" and doc["question"] != f"Q{validity}"):
            return Response(response=json.dumps({"Error": "You don't have access to this document"}), status=401)

        # add the right version if requested, otherwise use last one by default
        # (without the annotations stored in the db)
        file_path = doc["rel_filepath"]
        # if annotations are requested, use last version as it's the only one with annotations not separated
        if request_form.get("with_annotations") is None:
            last_version = get_last_version(job_id, file_path)
            version = int(request_form.get("version", last_version))  # use last_version by default
            print("Query version for:", {"job_id": job_id, "rel_filepath": file_path, "version": version})
            vers = db["versions"].find_one(
                {"job_id": job_id, "rel_filepath": file_path, "version": version}
            )
            if vers:
                print("Found version:", vers["version_filepath"])
                file_path = storage.rel_path(vers["version_filepath"])
            else:
                return Response(response=json.dumps({"Error": "You don't request a valid version"}), status=400)
        elif request_form.get("version") is not None:
            return Response(response=json.dumps({"Error": "You cannot request with annotations and a version at the same time."}), status=400)
    else:
        if validity is not None and validity != "mat" and validity != "all":
            return Response(response=json.dumps({"Error": "You don't have access to this question"}), status=401)
        doc = db["job_documents"].find_one({"job_id": job_id, "document_index": document_index})
        if doc is None:
            return Response(
                response=json.dumps({"response": "No document found!"}),
                status=404,
            )
        file_path = doc["rel_filepath"]

    print("document_file: ", doc)
    return send_file(storage.abs_path(file_path))


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

    last_version = get_last_version(job_id, question_file["rel_filepath"])

    return Response(response=json.dumps({"last_version": last_version}), status=200)


def get_last_version_document(rel_filepath):
    version_base = version_basename(rel_filepath)
    filename_base = storage.abs_path(version_base)
    # print("file_base", filename_base)
    all_versions = glob.glob(filename_base + "-*.pdf")
    return len(all_versions) - 1


def get_last_version(job_id, rel_filepath):
    db = mongo["RMN"]
    return db["versions"].count_documents({"job_id": job_id, "rel_filepath": rel_filepath}) - 1


@app.route("/document/annotations", methods=["POST"])
@cross_origin()
@verify_share_token(return_validity=True)
def document_annotations(validity):
    request_form = request.form

    if "job_id" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: job_id not provided."}),
            status=400,
        )
    if "document_index" not in request_form:
        return Response(
            response=json.dumps({"response": "Error: document_index not provided."}),
            status=400,
        )

    job_id = str(request_form["job_id"])
    document_index = int(request_form["document_index"])

    db = mongo["RMN"]
    coll = db["job_questions"] if request_form.get("questions") is not None else db["job_documents"]
    doc = coll.find_one({"job_id": job_id, "document_index": document_index})

    if doc is None:
        return Response(
            response=json.dumps({"response": "No document found!"}),
            status=404,
        )

    # validity = None => logged user
    if not question_allowed(validity, doc["question_index"]):
        return Response(response=json.dumps({"Error": "You don't have access to this document"}), status=404)

    rel_filepath = doc["rel_filepath"]
    last_version = get_last_version(job_id, rel_filepath)
    version = int(request_form.get("version", last_version))  # use last_version by default
    query = {"job_id": job_id, "rel_filepath": rel_filepath, "version": version}
    print("Query versions for", query)
    vers = db["versions"].find_one(query)
    if vers is None:
        return Response(response=json.dumps({"response": "No version found!"}), status=200)

    return Response(response=json.dumps({
        'annotations': vers["annotations"],
        "last_version": last_version}
    ), status=200)


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

    # scope to the requesting user (before mutating documents/status) so one
    # user cannot validate another's job
    db = mongo["RMN"]
    if db["eval_jobs"].find_one({"job_id": job_id, "user_id": user_id}) is None:
        return Response(
            response=json.dumps({"response": f"Error: job {job_id} for user {user_id} doesn't exist."}),
            status=404,
        )

    # set all estimation to 0
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
    """Remove all storage and database records for a job (synchronous).

    /job/delete offloads this to an executor via the queue; delete_old_jobs
    (admin sweep) and the enqueue fallback call it directly.
    """
    print("Delete job:", job_id)

    # remove any queued reference to the job so the executor never picks it up
    # (payloads must match the exact strings pushed to the queue)
    try:
        redis.lrem("job_queue", 0, json.dumps({"job_id": job_id}))
        redis.lrem("job_queue", 0, json.dumps({"job_id": job_id, "add_copies": True}))
    except Exception as e:
        print(e)

    try:
        # targeted per-job deletion; remove_all_match walked the whole storage
        # tree on every call and made concurrent deletes hang the worker
        storage.remove_job(job_id)
    except Exception as e:
        print(e)

    db = mongo["RMN"]
    for collection in ("job_documents", "job_questions", "eval_jobs", "jobs_output", "versions"):
        try:
            db[collection].delete_many({"job_id": job_id})
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
            status=404
        )

    # Remove the job record synchronously so it disappears from listings right
    # away and any running executor sees it as deleted (StopHandler), then hand
    # the heavy storage + collection cleanup to an executor via the queue so the
    # request returns immediately and never blocks the (NFS-bound) web worker.
    collection.delete_many({"user_id": user_id, "job_id": job_id})
    try:
        redis.rpush("job_queue", json.dumps({"job_id": job_id, "delete": True}))
    except Exception as e:
        # if the queue is unreachable, still keep the cleanup off the request
        # path by running it in a background thread rather than inline
        print("Failed to enqueue delete task; cleaning up in a background thread:", e)
        Thread(target=delete_job, args=[job_id]).start()

    #
    return Response(response=json.dumps({"response": "OK"}), status=200)


def delete_old_jobs(n_days_old=0, user_id=None):
    db = mongo["RMN"]
    collection = db["eval_jobs"]
    r = {} if user_id is None else {"user_id": user_id}
    jobs = collection.find(r)

    now = dt.datetime.now(dt.UTC)
    n = 0
    for j in jobs:
        delta = now - j["queued_time"].replace(tzinfo=dt.UTC)
        if delta.days >= n_days_old:
            delete_job(j["job_id"])
            n = n + 1

    return n


@app.route("/admin/delete/jobs", methods=["POST"])
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


@app.route("/admin/signup", methods=["POST"])
@cross_origin()
@verify_admin
def admin_signup():
    db = mongo["RMN"]
    return UserService.signup(request, db)


@app.route("/admin/delete/tokens", methods=["POST"])
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


@app.route("/admin/delete/user", methods=["POST"])
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


@app.route("/admin/users", methods=["POST"])
@cross_origin()
@verify_admin
def admin_users():
    db = mongo["RMN"]
    all_users = UserService.users(db)
    return Response(response=json.dumps({"response": "OK", "users": all_users}), status=200)


@app.route("/admin/change_password", methods=["POST"])
@cross_origin()
@verify_admin
def admin_change_password():
    db = mongo["RMN"]
    return UserService.change_password(request, db, False)

@app.route("/admin/template", methods=["POST"])
@cross_origin()
@verify_admin
def create_default_template():
    db = mongo["RMN"]
    return TemplateService.add_default_templates(request.form.get('user_id'), db, storage)


@app.route("/admin/storage/clean", methods=["POST"])
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


@app.route("/admin/executor", methods=["GET"])
@cross_origin()
@verify_admin
def admin_executor():
    redis.rpush("job_queue", "{}")
    return Response(response=json.dumps({"response": "OK"}), status=200)

# limits of the moodle zip sent to /front_page: the archive was extracted with
# no budget (a small zip can inflate to fill the disk)
FRONT_PAGE_MAX_MEMBERS = 5000
FRONT_PAGE_MAX_UNZIPPED_BYTES = 4 * 1024 ** 3


def extract_bounded(zip_path, dest, max_members=None, max_bytes=None):
    """Extract ``zip_path`` into ``dest``; the error message when it exceeds the budget.

    The declared sizes are summed before anything is written. Member names
    are made safe by ``ZipFile.extract`` itself (``..`` and absolute paths are
    stripped). The limits default to the module constants at call time.
    """
    max_members = FRONT_PAGE_MAX_MEMBERS if max_members is None else max_members
    max_bytes = FRONT_PAGE_MAX_UNZIPPED_BYTES if max_bytes is None else max_bytes
    with ZipFile(zip_path, "r") as zip_ref:
        members = zip_ref.infolist()
        if len(members) > max_members:
            return f"Error: the zip has {len(members)} members (max {max_members})."
        total = sum(m.file_size for m in members)
        if total > max_bytes:
            return f"Error: the zip inflates to {total} bytes (max {max_bytes})."
        zip_ref.extractall(dest)
    return None


@app.route("/front_page", methods=["POST"])
@cross_origin()
@verify_token()
def front_page(user_id):
    """Add a LaTeX cover page to every copy of a Moodle zip; returns the new zip.

    Needs pdflatex in the image (the published server image has none, so the
    endpoint answers 501 rather than pretending). Everything happens in a
    directory created for this request and removed afterwards: the working
    directory used to be named after the user, so two requests of one user
    shared it and the user name was a path component.
    """
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

    if shutil.which(FrontPageHandler.CMD) is None:
        return Response(
            response=json.dumps({"response": "Error: LaTeX (pdflatex) is not installed on the server."}),
            status=501,
        )

    suffix = str(request_form["suffix"])
    moodle_zip = request.files.get("moodle_zip")
    latex_front_page = request.files.get("latex_front_page")

    os.makedirs(FRONT_PAGE_TEMP_FOLDER, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=f"{secure_filename(user_id) or 'user'}_", dir=FRONT_PAGE_TEMP_FOLDER))
    try:
        # streamed to disk: the zip used to be read whole into memory
        moodle_zip_path = work_dir.joinpath("moodle.zip")
        moodle_zip.save(str(moodle_zip_path))
        content_dir = work_dir.joinpath("moodle")
        content_dir.mkdir()
        error = extract_bounded(moodle_zip_path, content_dir)
        if error:
            return Response(response=json.dumps({"response": error}), status=413)
        moodle_zip_path.unlink()

        latex_front_page_path = work_dir.joinpath(secure_filename(latex_front_page.filename) or "front_page.tex")
        latex_front_page.save(FileIO(latex_front_page_path, "wb"))
        shutil.copy(LATEX_INPUT_FILE, work_dir)
        latex_input_file = work_dir.joinpath("data.tex")

        handler = FrontPageHandler()
        done, failed = handler.addFrontPages(
            str(work_dir), str(content_dir), suffix, str(latex_front_page_path), str(latex_input_file)
        )
        # a failure is reported, not hidden behind a 200 with an incomplete zip
        if failed or not done:
            return Response(
                response=json.dumps({"response": f"Error: {failed} copie(s) sans page couverture, {done} réussie(s)."}),
                status=500,
            )

        archive = shutil.make_archive(str(work_dir.joinpath("moodle")), "zip", content_dir)
        # send_file opens the archive now; the directory can go
        return send_file(archive, download_name="moodle.zip", as_attachment=True)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    # the debugger exposes a console on any unhandled exception: opt in only
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
