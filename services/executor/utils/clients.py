import os
import json
from copy import copy
import redis
import socketio
from pymongo import MongoClient


mongodb_user = os.getenv("MONGODB_USER", "adminuser")
mongodb_pass = os.getenv("MONGODB_PASSWORD", "example")
mongodb_host = "mongo" if os.getenv("ENVIRONMENT") == "production" else "localhost"
mongo_url = f"mongodb://{mongodb_user}:{mongodb_pass}@{mongodb_host}:27017/?retryWrites=true&w=majority"

redis_host = "redis" if os.getenv("ENVIRONMENT") == "production" else "localhost"
socketio_host = (
    "socketio" if os.getenv("ENVIRONMENT") == "production" else "localhost"
)


def mongo_client():
    return MongoClient(mongo_url)


def redis_client():
    return redis.Redis(host=redis_host)


def socketio_client():
    sio = socketio.Client()
    sio.connect(f"http://{socketio_host}:7000")
    return sio


def emit_job(sio, user_id, job_id, status, infos=None, sio_infos=None):
    if infos is None and sio_infos is None:
        sio_infos = {}
    elif infos is not None:
        if sio_infos is not None:
            sio_infos.update(infos)
        else:
            sio_infos = copy(infos)

    sio_infos["user_id"] = user_id
    sio_infos["job_id"] = job_id
    sio_infos["status"] = status.value
    sio.emit("job_status", json.dumps(sio_infos))


def update_status(db, sio, user_id, job_id, status, infos=None, db_infos=None, sio_infos=None):
    # initialize db_infos
    if infos is None and db_infos is None:
        db_infos = {}
    elif infos is not None:
        if db_infos is not None:
            db_infos.update(infos)
        else:
            db_infos = copy(infos)
    # update db status
    db_infos["job_status"] = status.value
    db.get_collection("eval_jobs").update_one(
        {"job_id": job_id},
        {"$set": db_infos}
    )
    # emit status
    emit_job(sio, user_id, job_id, status, infos, sio_infos)
