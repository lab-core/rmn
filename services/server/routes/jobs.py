"""A task from its creation to its validation: settings, sharing, status."""

import datetime as dt
import glob
import json
import os
import shutil
import uuid
import zipfile
from io import FileIO
from threading import Thread
from zipfile import ZipFile
import pandas as pd
from flask import Blueprint, Response, request, send_file
from flask_cors import cross_origin
from werkzeug.utils import secure_filename
from rmn_common import auto_grade
from rmn_common.moodle import MoodleFields as MF
from rmn_common.questions import validate_bonus_map, validate_questions
from rmn_common.status import Document_Status, Job_Status
from auth import verify_share_token, verify_token
from context import TEMP_FOLDER, mongo, redis, sio, storage
from service.job_cleanup import delete_job
from utils.uploads import save_csv, temp_upload_path


bp = Blueprint("jobs", __name__, url_prefix="/jobs")


def stored_zips(job_id):
    """Every zip stored for a task, storage-relative.

    The current layout is a directory per task; a task old enough predates it
    and has a single ``zips/<job_id>.zip`` (see ``Storage._JOB_FILES``).
    """
    directory = os.path.join("zips", job_id)
    absolute = storage.abs_path(directory)
    if os.path.isdir(absolute):
        return sorted(
            os.path.join(directory, name)
            for name in os.listdir(absolute)
            if name.endswith(".zip")
        )
    legacy = os.path.join("zips", f"{job_id}.zip")
    return [legacy] if os.path.isfile(storage.abs_path(legacy)) else []


def stored_copies(job_id):
    """The whole copies of a task, storage-relative.

    The executor deletes each zip as soon as it has split it
    (``utils.split.insert_copies``) and moves every copy, under the name it
    had inside the zip, to ``documents/<job_id>/all``. So a task that has been
    processed -- which is every task worth duplicating -- keeps its copies
    there and nowhere else.
    """
    folder = os.path.join("documents", job_id, "all")
    absolute = storage.abs_path(folder)
    if not os.path.isdir(absolute):
        return []
    return sorted(
        os.path.join(folder, name)
        for name in os.listdir(absolute)
        if name.lower().endswith(".pdf")
    )


def zip_stored_copies(copies, zip_file_id):
    """Write ``copies`` into a new stored zip, the way they were uploaded.

    Stored, not deflated: the pdfs are compressed already, and the archive is
    read once by the executor and then deleted.
    """
    absolute = storage.abs_path(zip_file_id)
    os.makedirs(os.path.dirname(absolute), exist_ok=True)
    with zipfile.ZipFile(absolute, "w", zipfile.ZIP_STORED) as archive:
        for copy in copies:
            archive.write(storage.abs_path(copy), os.path.basename(copy))
    return absolute


@bp.route("/evaluate", methods=["POST"])
@cross_origin()
@verify_token()
def evaluate(user_id):
    """Create a task and queue it for splitting.

    Form fields: the templates, the per-question pages, points and bonus, the
    name and the two switches; files: ``zip_file`` (the copies) and
    ``notes_csv_file`` (the Moodle export).

    ``source_job_id`` creates the task from an existing one of the same user:
    each of the two files it does not carry is taken from that task, so the
    same copies and the same notes can be corrected again -- with any other
    setting changed, since all of them still come from the form. A file that
    *is* uploaded wins, which is how one of the two is replaced.

    The copies come from the source's zips while it still has them, and
    otherwise from the pdfs they were split into (``stored_copies``), which is
    what a task that has been processed keeps.
    """
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

    # A task can be created from an existing one: whatever is not uploaded is
    # taken from that task's own files. Everything else -- name, templates,
    # questions -- is sent by the form, so the user can change any of it.
    source_job_id = str(request_form.get("source_job_id", "")).strip()
    source_csv = None
    source_zips = []
    source_copies = []
    if source_job_id:
        source = mongo["RMN"]["eval_jobs"].find_one(
            {"job_id": source_job_id, "user_id": user_id}
        )
        if source is None:
            return Response(
                response=json.dumps(
                    {"response": f"Error: job {source_job_id} for user {user_id} doesn't exist."}
                ),
                status=404,
            )
        if "notes_csv_file" not in request.files:
            source_csv = source.get("notes_file_id") or os.path.join(
                "csv", f"{source_job_id}.csv"
            )
            if not os.path.isfile(storage.abs_path(source_csv)):
                return Response(
                    response=json.dumps(
                        {"response": "Error: la liste de notes de la tâche "
                         "d'origine n'est plus disponible."}
                    ),
                    status=400,
                )
        if "zip_file" not in request.files:
            source_zips = stored_zips(source_job_id)
            if not source_zips:
                # the usual case: the task was split, so its zip is gone
                source_copies = stored_copies(source_job_id)
            if not source_zips and not source_copies:
                return Response(
                    response=json.dumps(
                        {"response": "Error: les copies de la tâche d'origine "
                         "ne sont plus disponibles."}
                    ),
                    status=400,
                )

    if not request.files and not source_job_id:
        return Response(
            response=json.dumps({"response": "Error: No files provided."}),
            status=400,
        )

    inherited = {
        "notes_csv_file": source_csv is not None,
        "zip_file": bool(source_zips or source_copies),
    }
    for file_field in ("notes_csv_file", "zip_file"):
        if file_field not in request.files and not inherited[file_field]:
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
        if source_csv:
            # already normalised to a comma separator when it was first stored
            storage.copy_inside(source_csv, notes_file_id)
        else:
            notes_csv_file = request.files.get("notes_csv_file")
            notes_csv_file_name = temp_upload_path(notes_csv_file.filename)
            notes_csv_file.save(FileIO(notes_csv_file_name, "wb"))
            save_csv(str(notes_csv_file_name), notes_file_id)

        if source_zips:
            # copied, not shared: deleting either task must take only its own
            # files, and the executor extracts each task's zips into its tree
            for stored in source_zips:
                storage.copy_inside(
                    stored, os.path.join("zips", job_id, f"{uuid.uuid4()}.zip")
                )
        elif source_copies:
            zip_stored_copies(
                source_copies, os.path.join("zips", job_id, f"{uuid.uuid4()}.zip")
            )
        else:
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


@bp.route("", methods=["POST"])
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


@bp.route("/info", methods=["POST"])
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
        # so a task created from this one opens with the same switch
        "validate_matricule": job.get("validate_matricule", True),
        "groups": job.get("groups", [""]),
        "copies_errors": job.get("copies_errors"),
        # how far the grade reading has got, question by question, so the
        # dashboard and the correction screen can say what is waiting on what
        "auto_grade_progress": auto_grade.progress(db["job_questions"], job_id),
    }
    return Response(response=json.dumps({"response": resp}), status=200)


@bp.route("/share", methods=["POST"])
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


@bp.route("/unshare", methods=["POST"])
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


@bp.route("/update/bonus", methods=["POST"])
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


# once validated, the points are baked into the output (csv, stats pages)
POINTS_LOCKED_STATUSES = (Job_Status.VALIDATED.value, Job_Status.FINALIZING.value, Job_Status.ARCHIVED.value)


JOB_NAME_MAX_LENGTH = 200


def _settings_error(message, status=400):
    return Response(response=json.dumps({"response": f"Error: {message}"}), status=status)


def _resplit_rejected_copies(job_id):
    """Queue the copies rejected for their page count to be split again.

    They wait in incorrect_files/<job_id>/ (utils/split.py); they are zipped
    into zips/<job_id>/, where the executor looks for copies to add, like an
    upload from the retry dialog. Returns how many there were.
    """
    rejected = sorted(glob.glob(storage.abs_path(os.path.join("incorrect_files", job_id, "*.pdf"))))
    if rejected:
        zip_path = storage.abs_path(os.path.join("zips", job_id, f"{uuid.uuid4()}.zip"))
        os.makedirs(os.path.dirname(zip_path), exist_ok=True)
        with ZipFile(zip_path, "w") as new_zip:
            for pdf in rejected:
                new_zip.write(pdf, os.path.basename(pdf))
    storage.remove_tree(os.path.join("incorrect_files", job_id))
    redis.rpush("job_queue", json.dumps({"job_id": job_id, "add_copies": True}))
    return len(rejected)


@bp.route("/update/settings", methods=["POST"])
@cross_origin()
@verify_token()
def update_job_settings(user_id):
    """Change a task's name, points or pages per question while they can still matter.

    Form fields, each optional (at least one): ``job_name``;
    ``n_max_points_per_question`` and ``n_pages_per_question`` as JSON
    ``[["Q1", value], ...]`` with the task's own questions.

    - the name is only displayed: it can always change;
    - the points are read by the grade reader and at finalization: they can
      change until the task is validated. A grade now above its question's
      maximum (bonus questions aside) goes back to "à valider";
    - the pages decide how every copy is cut: they can only change while no
      copy has been split, i.e. when all were rejected for their page count
      (RETRY). The rejected copies are then split again.
    """
    form = request.form
    job_id = str(form.get("job_id", ""))
    if not job_id:
        return _settings_error("job_id not provided.")
    db = mongo["RMN"]
    job = db["eval_jobs"].find_one({"job_id": job_id, "user_id": user_id})
    if job is None:
        return _settings_error(f"job {job_id} for user {user_id} doesn't exist.", 404)
    status = job["job_status"]
    updates = {}

    if "job_name" in form:
        name = form["job_name"].strip()
        if not name or len(name) > JOB_NAME_MAX_LENGTH:
            return _settings_error(f"le nom de la tâche doit faire de 1 à {JOB_NAME_MAX_LENGTH} caractères.")
        updates["job_name"] = name

    pages = job.get("n_pages_per_question", [])
    points = job.get("n_max_points_per_question", [])
    for field in ("n_max_points_per_question", "n_pages_per_question"):
        if field not in form:
            continue
        try:
            value = json.loads(form[field])
        except ValueError:
            return _settings_error(f"{field} is not JSON.")
        if field == "n_max_points_per_question":
            if status in POINTS_LOCKED_STATUSES:
                return _settings_error("les points ne peuvent plus changer : la tâche est validée.", 409)
            points = value
        else:
            if status != Job_Status.RETRY.value:
                return _settings_error(
                    "le nombre de pages ne peut changer que lorsque les copies ont été refusées pour leur "
                    "nombre de pages.", 409)
            if db["job_questions"].count_documents({"job_id": job_id}) > 0:
                return _settings_error(
                    "des copies ont déjà été découpées avec l'ancien nombre de pages : elles le seraient "
                    "différemment des suivantes.", 409)
            pages = value
        updates[field] = value

    if "n_max_points_per_question" in updates or "n_pages_per_question" in updates:
        # the bonus map carries the task's questions: the keys cannot change
        error = validate_questions(pages, points, job.get("bonus_enabled_map", []))
        if error:
            return _settings_error(error)
    if not updates:
        return _settings_error("rien à modifier.")

    query = {"$set": updates}
    if "n_pages_per_question" in updates:
        query["$set"]["job_status"] = Job_Status.CORRECTED.value
        query["$unset"] = {"copies_errors": "", "job_infos": ""}
    # conditional on the status read above: an executor that moved the task on
    # meanwhile wins, and the teacher is told to try again
    result = db["eval_jobs"].update_one({"job_id": job_id, "user_id": user_id, "job_status": status}, query)
    if result.matched_count == 0:
        return _settings_error("la tâche a changé d'état entre-temps, réessayez.", 409)

    flagged = 0
    if "n_max_points_per_question" in updates:
        bonus = dict(job.get("bonus_enabled_map", []))
        for key, max_points in points:
            if bonus.get(key):
                continue  # a bonus question is meant to go above its points
            flagged += db["job_questions"].update_many(
                {
                    "job_id": job_id,
                    "question_index": int(key[1:]),
                    "grade": {"$gt": max_points},
                    "status": {"$in": [Document_Status.VALIDATED.value, Document_Status.HIGH_ACCURACY.value]},
                },
                {"$set": {"status": Document_Status.TO_VALIDATE.value}},
            ).modified_count

    resplit = _resplit_rejected_copies(job_id) if "n_pages_per_question" in updates else 0

    return Response(response=json.dumps({"response": "OK", "flagged": flagged, "resplit": resplit}), status=200)


@bp.route("/update/stats", methods=["POST"])
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


@bp.route("/update/csv", methods=["POST"])
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


@bp.route("/update/status", methods=["POST"])
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


@bp.route("/ignore", methods=["POST"])
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


@bp.route("/continue", methods=["POST"])
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


@bp.route("/validate", methods=["POST"])
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


@bp.route("/delete", methods=["POST"])
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


@bp.route("/batch/info", methods=["POST"])
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


@bp.route("/incorrect/download", methods=["POST"])
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
