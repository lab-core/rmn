"""Status updates: what is written to Mongo and what is pushed over Socket.IO."""

import json
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

    update_status(Database(), sio, "alice", "job", Job_Status.ERROR,
                  infos={"job_infos": "boom"}, db_infos={"retry": 3})

    job = mongo_db["eval_jobs"].find_one({"job_id": "job"})
    assert job["job_status"] == "ERROR"
    assert job["job_infos"] == "boom"
    assert job["retry"] == 3
    payload = _payload(sio)
    assert payload["status"] == "ERROR" and payload["job_infos"] == "boom"
    assert "retry" not in payload  # db-only detail
