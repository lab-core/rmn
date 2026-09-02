from flask import Flask, request
from flask_socketio import SocketIO, send, emit, join_room, leave_room
from pymongo import MongoClient
import os
import json
import eventlet
# Patch networking for eventlet, but leave select/thread alone so pymongo can
# still use select.poll and its own monitor threads (monkey_patch() otherwise
# removes select.poll and breaks the Mongo driver under eventlet).
eventlet.monkey_patch(select=False, thread=False)

# --- configuration -----------------------------------------------------------

# Shared secret the backend (server/executor) presents so that ONLY it may push
# notifications. Without it those emit handlers are treated as untrusted.
SERVICE_TOKEN = os.getenv("SOCKETIO_SERVICE_TOKEN")

# Restrict which origins may open a socket. Defaults to "*" so local dev keeps
# working; set SOCKETIO_CORS_ORIGINS (comma-separated) in production.
_cors = os.getenv("SOCKETIO_CORS_ORIGINS", "*")
cors_allowed_origins = "*" if _cors.strip() == "*" else [o.strip() for o in _cors.split(",") if o.strip()]

# Mongo is used to validate user tokens and authorize room joins.
mongodb_user = os.getenv("MONGODB_USER", "adminuser")
mongodb_pass = os.getenv("MONGODB_PASSWORD", "example")
mongodb_host = "mongo" if os.getenv("ENVIRONMENT") == "production" else "localhost"
mongo = MongoClient(f"mongodb://{mongodb_user}:{mongodb_pass}@{mongodb_host}:27017/?retryWrites=true&w=majority")


app = Flask(__name__)
# logger/engineio_logger off: they dump raw handshake packets, which would leak
# the service token and user tokens sent in the auth payload.
socketio = SocketIO(app, logger=False, engineio_logger=False, policy_server=False,
                    async_mode='eventlet', manage_session=False,
                    cors_allowed_origins=cors_allowed_origins)

# Per-connection identity, keyed by socket id.
#   {"role": "service"}                        -> the backend, may push events
#   {"role": "user", "user_id": <username>}    -> a logged-in browser
#   {"role": "share", "share_token": <token>}  -> a share-link browser
#   {"role": "anonymous"}                       -> no valid credential
connections = {}


# --- authentication / authorization ------------------------------------------

def identify(auth):
    """Map the handshake ``auth`` payload to a connection identity."""
    auth = auth or {}
    if SERVICE_TOKEN and auth.get("service_token") == SERVICE_TOKEN:
        return {"role": "service"}

    token = auth.get("token")
    if token:
        record = mongo["RMN"]["tokens"].find_one({"token": token})
        if record and (not auth.get("user_id") or auth.get("user_id") == record["username"]):
            return {"role": "user", "user_id": record["username"]}

    share_token = auth.get("share_token")
    if share_token:
        return {"role": "share", "share_token": share_token}

    return {"role": "anonymous"}


def can_join(identity, room):
    """Whether ``identity`` is allowed to join ``room`` (a user_id, job_id or
    template_id)."""
    role = identity.get("role")
    if role == "service":
        return True

    db = mongo["RMN"]
    if role == "user":
        user_id = identity["user_id"]
        # own notification room, or a job / template the user owns
        if room == user_id:
            return True
        if db["eval_jobs"].find_one({"job_id": room, "user_id": user_id}):
            return True
        if db["template"].find_one({"template_id": room, "user_id": user_id}):
            return True
        return False

    if role == "share":
        token = identity["share_token"]
        job = db["eval_jobs"].find_one({"job_id": room})
        if job and token in (job.get("share_token", {}) or {}).values():
            return True
        out = db["jobs_output"].find_one({"job_id": room})
        if out and out.get("share_token") == token:
            return True
        return False

    return False


def is_service():
    return connections.get(request.sid, {}).get("role") == "service"


# --- socket handlers ---------------------------------------------------------

@socketio.on("connect")
def on_connection(auth):
    identity = identify(auth)
    connections[request.sid] = identity
    print(f"Connected ({identity.get('role')})")


@socketio.on("disconnect")
def on_disconnect():
    connections.pop(request.sid, None)


@socketio.on("join")
def on_join(room):
    identity = connections.get(request.sid, {"role": "anonymous"})
    if can_join(identity, room):
        join_room(room)
        print(f"Joined room {room}")
    else:
        print(f"Denied join to room {room} for {identity.get('role')}")


@socketio.on("leave")
def on_leave(room):
    leave_room(room)
    print(f"Left room {room}")


@socketio.on("document_ready")
def handle_message(data):
    if not is_service():
        return
    job_id = json.loads(data)["job_id"]
    emit("document_ready", data, room=job_id)
    print(f"Received data: {data} to room : {job_id}")


@socketio.on("job_status")
def handle_job_status_change(data):
    if not is_service():
        return
    message = json.loads(data)
    emit("job_status", data, room=message["user_id"])
    emit("job_status", data, room=message["job_id"])
    print(f"Received data: {data} to room : {message['user_id']}")


@socketio.on("template_rendered")
def handle_template_rendered_change(data):
    if not is_service():
        return
    template_id = json.loads(data)["template_id"]
    emit("template_rendered", data, room=template_id)
    print(f"Received data: {data} to room : {template_id}")


@socketio.on("doc_validated")
def handle_doc_validated(data):
    if not is_service():
        return
    job_id = json.loads(data)["job_id"]
    emit("doc_validated", data, room=job_id)
    print(f"Received data: {data} to room : {job_id}")


if __name__ == "__main__":
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('', 7000)), app)
