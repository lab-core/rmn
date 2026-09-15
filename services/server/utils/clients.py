import os
import redis
import socketio
from pymongo import MongoClient


mongodb_host = "mongo" if os.getenv("ENVIRONMENT") == "production" else "localhost"


def mongo_url():
    """The MongoDB URL from MONGODB_USER / MONGODB_PASSWORD.

    Fails closed: the credentials used to default to adminuser / example, so a
    missing variable silently connected with the sample password.
    """
    user = os.getenv("MONGODB_USER")
    password = os.getenv("MONGODB_PASSWORD")
    if not user or not password:
        raise RuntimeError("MONGODB_USER and MONGODB_PASSWORD must be set")
    return f"mongodb://{user}:{password}@{mongodb_host}:27017/?retryWrites=true&w=majority"


redis_host = "redis" if os.getenv("ENVIRONMENT") == "production" else "localhost"
socketio_host = "socketio" if os.getenv("ENVIRONMENT") == "production" else "localhost"


def mongo_client():
    return MongoClient(mongo_url())


def redis_client(**options):
    """Return a Redis client for the job queue.

    Args:
        **options: Extra ``redis.Redis`` keyword arguments, e.g.
            ``socket_connect_timeout`` / ``socket_timeout`` for callers that
            must not block when Redis is down (redis-py has no default
            timeouts).
    """
    # password is optional so an unauthenticated Redis still works in dev
    return redis.Redis(
        host=redis_host,
        port=6379,
        db=0,
        password=os.getenv("REDIS_PASSWORD") or None,
        **options,
    )


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
        print(
            "WARNING: SOCKETIO_SERVICE_TOKEN is not set; socketIO events "
            "will be dropped",
            flush=True,
        )
    return token


def socketio_client():
    sio = socketio.Client()
    # authenticate as the trusted backend so the socket server relays our events
    sio.connect(
        f"http://{socketio_host}:7000", auth={"service_token": socketio_service_token()}
    )
    return sio
