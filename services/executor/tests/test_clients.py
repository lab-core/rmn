"""Status updates: what is written to Mongo and what is pushed over Socket.IO."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from process_copy.database import Database
from utils.clients import emit_job, update_status
from rmn_common.status import Job_Status


def _payload(sio):
    event, payload = sio.emit.call_args.args
    assert event == "job_status"
    return json.loads(payload)


def test_emit_job_payload():
    sio = MagicMock()
    emit_job(sio, "alice", "job", Job_Status.RUN, infos={"job_infos": "x"})
    assert _payload(sio) == {"job_infos": "x", "user_id": "alice", "job_id": "job", "status": "RUN"}


def test_emit_job_merges_and_does_not_mutate_the_callers_dicts():
    sio = MagicMock()
    infos = {"a": 1}
    sio_infos = {"b": 2}
    emit_job(sio, "alice", "job", Job_Status.ERROR, infos=infos, sio_infos=sio_infos)
    payload = _payload(sio)
    assert payload["a"] == 1 and payload["b"] == 2 and payload["status"] == "ERROR"
    assert infos == {"a": 1}


def test_update_status_writes_the_db_and_emits(mongo_db):
    mongo_db["eval_jobs"].insert_one({"job_id": "job", "user_id": "alice", "job_status": "QUEUED"})
    sio = MagicMock()

    update_status(Database(), sio, "alice", "job", Job_Status.ERROR, infos={"job_infos": "boom"}, db_infos={"retry": 3})

    job = mongo_db["eval_jobs"].find_one({"job_id": "job"})
    assert job["job_status"] == "ERROR"
    assert job["job_infos"] == "boom"
    assert job["retry"] == 3
    payload = _payload(sio)
    assert payload["status"] == "ERROR" and payload["job_infos"] == "boom"
    assert "retry" not in payload  # db-only detail


def test_mongo_url_requires_credentials(monkeypatch):
    # the defaults were adminuser / example: a missing variable connected with
    # the sample password instead of failing
    import pytest

    import utils.clients as clients

    monkeypatch.delenv("MONGODB_USER", raising=False)
    monkeypatch.delenv("MONGODB_PASSWORD", raising=False)
    with pytest.raises(RuntimeError):
        clients.mongo_url()
    monkeypatch.setenv("MONGODB_USER", "u")
    monkeypatch.setenv("MONGODB_PASSWORD", "p")
    assert clients.mongo_url().startswith("mongodb://u:p@")


def test_requests_is_a_runtime_dependency():
    # python-engineio's client does its polling handshake through requests but
    # does not require it; #159 dropped it with TensorFlow and every executor
    # of the image failed with "namespaces failed to connect". Checked in the
    # file, since the test venv may get requests from another package.
    requirements = Path(__file__).resolve().parent.parent.joinpath("requirements.txt")
    names = {line.split("==")[0].strip().lower() for line in requirements.read_text().splitlines()
             if line.strip() and not line.startswith("#")}
    assert "requests" in names


def test_a_relay_that_is_down_does_not_fail_the_job(monkeypatch, capsys):
    """A socketIO outage used to kill the pod before it took a job.

    ``socketio_client()`` connected at import of the job and let the
    ConnectionError escape, so every executor started while socketIO was
    restarting died with "Connection refused" (October 2026).
    """
    import utils.clients as clients

    monkeypatch.setenv("SOCKETIO_SERVICE_TOKEN", "svc")

    class RefusingClient:
        connected = False

        def connect(self, url, auth):
            raise ConnectionError("Connection refused")

    monkeypatch.setattr(clients.socketio, "Client", RefusingClient)
    relay = clients.socketio_client()  # must not raise
    assert relay.connected is False
    assert relay.emit("job_status", "{}") is False
    assert "relay unreachable" in capsys.readouterr().out


def test_the_status_reaches_mongo_even_when_the_relay_is_down(mongo_db, monkeypatch):
    """Only the notification is lost; the webapp reads the state on refresh."""
    import utils.clients as clients

    monkeypatch.setenv("SOCKETIO_SERVICE_TOKEN", "svc")

    class RefusingClient:
        connected = False

        def connect(self, url, auth):
            raise ConnectionError("Connection refused")

    monkeypatch.setattr(clients.socketio, "Client", RefusingClient)
    mongo_db["eval_jobs"].insert_one({"job_id": "job", "user_id": "alice"})

    update_status(Database(), clients.socketio_client(), "alice", "job", Job_Status.ERROR)

    assert mongo_db["eval_jobs"].find_one({"job_id": "job"})["job_status"] == "ERROR"
