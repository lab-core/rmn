"""What the whole server talks to, created once.

The clients and the paths were module globals of ``app.py``; every route and
every service needs them, and importing them from the app module would make
each of those import the routes back. They live here so nothing has to.
"""

from pathlib import Path
from service.user_service import UserService
from utils.clients import mongo_client, redis_client, socketio_client
from utils.storage import Storage


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

ROOT_DIR = Path(__file__).resolve().parent
TEMP_FOLDER = ROOT_DIR.joinpath("temp")
VALIDATE_TEMP_FOLDER = ROOT_DIR.joinpath("validate_temp_folder")
