from flask import Flask
from flask_socketio import SocketIO, send, emit, join_room, leave_room
from utils.utils import Client_Type
import os
import json
import eventlet
eventlet.monkey_patch()

# Restrict which origins may open a socket. Defaults to "*" (any origin) so
# local dev keeps working; set SOCKETIO_CORS_ORIGINS to a comma-separated list
# of allowed origins in production to stop arbitrary sites from connecting.
_cors = os.getenv("SOCKETIO_CORS_ORIGINS", "*")
cors_allowed_origins = "*" if _cors.strip() == "*" else [o.strip() for o in _cors.split(",") if o.strip()]

async_mode = None
app = Flask(__name__)
socketio = SocketIO(app, logger=True, engineio_logger=True, policy_server=False, async_mode='eventlet', manage_session=False, cors_allowed_origins=cors_allowed_origins)


@socketio.on("connect")
def on_connection(auth):
    print("Connected")


@socketio.on("join")
def on_join(room):
    # client_type = Client_Type(room)
    join_room(room)
    print(f"Joined room {room}")


@socketio.on("leave")
def on_leave(room):
    # client_type = Client_Type(room)
    leave_room(room)
    print(f"Left room {room}")


@socketio.on("document_ready")
def handle_message(data):
    # emit("document_ready", data, to=Client_Type.WEB_CLIENT.value)
    job_id = json.loads(data)["job_id"]
    emit("document_ready", data, room=job_id)
    print(f"Received data: {data} to room : {job_id}")


@socketio.on("job_status")
def handle_job_status_change(data):
    # emit for user
    message = json.loads(data)
    emit("job_status", data, room=message["user_id"])
    # emit for job
    emit("job_status", data, room=message["job_id"])
    print(f"Received data: {data} to room : {message["user_id"]}")


@socketio.on("template_rendered")
def handle_template_rendered_change(data):
    template_id = json.loads(data)["template_id"]
    emit("template_rendered", data, room=template_id)
    print(f"Received data: {data} to room : {template_id}")


@socketio.on("doc_validated")
def handle_doc_validated(data):
    job_id = json.loads(data)["job_id"]
    emit("doc_validated", data, room=job_id)
    print(f"Received data: {data} to room : {job_id}")


if __name__ == "__main__":
    # socketio.run(app, host="localhost", port=7000)
    import eventlet
    eventlet.monkey_patch()
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('', 7000)), app)
