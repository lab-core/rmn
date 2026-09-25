"""The copies themselves: what is served, replaced, annotated and graded."""

import json
import os
import re
import tempfile
from threading import Thread
from flask import Blueprint, Response, request, send_file
from flask_cors import cross_origin
from werkzeug.utils import secure_filename
from rmn_common import auto_grade
from rmn_common.status import Document_Status
from auth import question_allowed, verify_share_token
from context import mongo, redis, sio, storage
from service.documents import (
    replace_thread,
    skipped_questions,
    start_reading_grades,
)
from service.versions import get_last_version, save_new_pdf_version


bp = Blueprint("documents", __name__, url_prefix="/documents")


@bp.route("", methods=["POST"])
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
                "group": doc.get("group", ""),
                # how sure the executor is of the matricule it read (None for
                # copies read before it was stored, or typed by hand)
                "matricule_confidence": doc.get("matricule_confidence"),
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

@bp.route("/replace", methods=["POST"])
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


@bp.route("/read_grades", methods=["POST"])
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


@bp.route("/tag", methods=["POST"])
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


@bp.route("/update", methods=["POST"])
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
                # an UpdateResult is always truthy: `if not r` never fired
                if r.matched_count == 0:
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


@bp.route("/download", methods=["POST"])
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


@bp.route("/last_version", methods=["POST"])
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


@bp.route("/annotations", methods=["POST"])
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
