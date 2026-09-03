import os
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
    # password is optional so an unauthenticated Redis still works in dev
    return redis.Redis(host=redis_host, port=6379, db=0,
                       password=os.getenv("REDIS_PASSWORD") or None)


def socketio_service_token():
    """Return the shared secret that identifies us to the socketIO server.

    Without it the socket server treats us as an untrusted client and silently
    drops every event we emit, so a missing token in production is a
    misconfiguration we refuse to run with; in dev we only warn.
    """
    token = os.getenv("SOCKETIO_SERVICE_TOKEN")
    if not token:
        if os.getenv("ENVIRONMENT") == "production":
            raise RuntimeError(
                "SOCKETIO_SERVICE_TOKEN is not set: real-time updates would be "
                "silently dropped by the socketIO server"
            )
        print("WARNING: SOCKETIO_SERVICE_TOKEN is not set; socketIO events "
              "will be dropped", flush=True)
    return token


def socketio_client():
    sio = socketio.Client()
    # authenticate as the trusted backend so the socket server relays our events
    sio.connect(f"http://{socketio_host}:7000",
                auth={"service_token": socketio_service_token()})
    return sio
