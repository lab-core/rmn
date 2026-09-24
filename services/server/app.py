"""The Flask application: configuration, app-wide hooks, and the routes it serves.

The routes themselves live in ``routes/``, one module per part of the API,
and what they all talk to lives in ``context.py``. This file is the wiring.
"""

import json
import os

from flask import Flask, Response
from flask_cors import CORS

from routes.admin import bp as admin_bp
from routes.documents import bp as documents_bp
from routes.files import bp as files_bp
from routes.front_page import bp as front_page_bp
from routes.jobs import bp as jobs_bp
from routes.matricule import bp as matricule_bp
from routes.templates import bp as templates_bp
from routes.users import bp as users_bp
# The clients live in context.py so that the routes can import them without
# importing this module back. They are re-exported here because app is the
# composition root: what the server talks to is reachable from the module
# that builds it.
from context import mongo, redis, sio, storage  # noqa: F401
from service.health_check import start_health_check
from utils.clients import redis_client

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

# a Redis lock elects one gunicorn worker per tick of the Slack dead-man's
# switch. Dedicated client with short timeouts: the lock must fail open fast
# when Redis is down instead of hanging the tick (and the alert with it).
start_health_check(redis=redis_client(socket_connect_timeout=2, socket_timeout=2))

# One blueprint per part of the API. No url_prefix anywhere: the paths are
# the ones the webapp has always called.
for blueprint in (users_bp, templates_bp, jobs_bp, files_bp, matricule_bp,
                  documents_bp, admin_bp, front_page_bp):
    app.register_blueprint(blueprint)


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


if __name__ == "__main__":
    # the debugger exposes a console on any unhandled exception: opt in only
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
