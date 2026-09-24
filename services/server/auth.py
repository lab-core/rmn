"""Who the caller is, and what of a job they may touch.

The login token, the admin key and the share-link scope, in one place: every
route is guarded by one of these and they were written among the routes they
guard.
"""

import hmac
import json
import os
from functools import wraps
from flask import Response, request
from context import mongo
from service.user_service import UserService


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


# Shared operator secret guarding the /admin/* endpoints. These are
# server-side operator commands (create the first admin, reset a password,
# delete a user/jobs, ...) that carry a *target* user in their form fields,
# so they cannot be guarded by the per-user @verify_token. Requiring this
# secret means that merely reaching Flask (e.g. bypassing the nginx deny
# rule) is not enough to call them. Unset => admin endpoints are disabled.
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")


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
