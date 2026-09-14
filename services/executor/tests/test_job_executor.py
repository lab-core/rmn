"""Worker-side helpers of job_executor: heartbeat, digit images and the idle-job sweep."""

import datetime as dt
import json
import os
import time
from unittest.mock import MagicMock

import fakeredis

import job_executor
from job_executor import Heartbeat, check_for_idle_jobs_to_requeue, save_number_images
from process_copy.database import Database
from utils.storage import Storage


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"png")


# ------------------------------------------------------------------ heartbeat


def test_heartbeat_refreshes_alive_time_until_stopped(mongo_db):
    mongo_db["eval_jobs"].insert_one({"job_id": "job", "alive_time": dt.datetime(2000, 1, 1)})
    heartbeat = Heartbeat(Database(), "job")
    heartbeat._interval = 0.05  # the constructor floors it at 5 s

    with heartbeat:
        time.sleep(0.3)

    alive = mongo_db["eval_jobs"].find_one({"job_id": "job"})["alive_time"]
    assert alive > dt.datetime(2000, 1, 2)
    assert not heartbeat._thread.is_alive()


def test_heartbeat_interval_has_a_floor():
    assert Heartbeat(MagicMock(), "job", interval=1)._interval == 5
    assert Heartbeat(MagicMock(), "job")._interval == job_executor.MAX_IDLE_TIME // 3


def test_heartbeat_survives_a_failing_database():
    db = MagicMock()
    db.eval_jobs_collection.side_effect = RuntimeError("mongo down")
    heartbeat = Heartbeat(db, "job")
    heartbeat._interval = 0.05
    with heartbeat:
        time.sleep(0.2)
    assert db.eval_jobs_collection.called


# --------------------------------------------------------------- digit images


def test_save_number_images_keeps_only_single_digit_grades(storage_root):
    for i in range(3):
        _touch(str(storage_root / "unverified_numbers" / "job" / "0" / f"{i}.png"))

    save_number_images(Storage(), "job", 0, {"Q1": "7", "Q2": "12", "Q3": "3.5"})

    saved = os.listdir(storage_root / "numbers" / "7")
    assert len(saved) == 1 and saved[0].endswith(".png")
    unverified = storage_root / "unverified_numbers" / "job" / "0"
    assert not (unverified / "0.png").exists()
    assert (unverified / "1.png").exists() and (unverified / "2.png").exists()
    assert not (storage_root / "numbers" / "12").exists()


def test_save_number_images_swallows_bad_values(storage_root):
    # not a number, and a digit whose image is missing: neither may raise
    save_number_images(Storage(), "job", 0, {"Q1": "abc"})
    save_number_images(Storage(), "job", 0, {"Q1": "4"})
    # the target folder may have been created, but nothing was saved in it
    assert not any(p.is_file() for p in (storage_root / "numbers").rglob("*"))


# -------------------------------------------------------------- idle-job sweep


def _fake_backends(monkeypatch):
    """The sweep uses the module-level redis/sio created under __main__."""
    redis = fakeredis.FakeStrictRedis()
    sio = MagicMock()
    monkeypatch.setattr(job_executor, "redis", redis, raising=False)
    monkeypatch.setattr(job_executor, "sio", sio, raising=False)
    return redis, sio


def _queue(redis):
    return sorted(json.loads(p)["job_id"] for p in redis.lrange("job_queue", 0, -1))


def test_idle_jobs_are_requeued_and_the_lock_released(mongo_db, monkeypatch):
    redis, _ = _fake_backends(monkeypatch)
    now = dt.datetime.now(dt.UTC)
    stale = now - dt.timedelta(seconds=job_executor.MAX_IDLE_TIME + 60)
    mongo_db["eval_jobs"].insert_many(
        [
            {"job_id": "run-idle", "user_id": "alice", "job_status": "RUN", "alive_time": stale, "retry": 0},
            {"job_id": "fin-idle", "user_id": "alice", "job_status": "FINALIZING", "alive_time": stale},
            {"job_id": "run-alive", "user_id": "alice", "job_status": "RUN", "alive_time": now},
            {"job_id": "done", "user_id": "alice", "job_status": "VALIDATION", "alive_time": stale},
        ]
    )

    check_for_idle_jobs_to_requeue(Database(), sleep=False)

    jobs = {j["job_id"]: j for j in mongo_db["eval_jobs"].find()}
    assert jobs["run-idle"]["job_status"] == "QUEUED"
    assert jobs["run-idle"]["retry"] == 1
    assert jobs["fin-idle"]["job_status"] == "VALIDATION"
    assert jobs["run-alive"]["job_status"] == "RUN"
    assert jobs["done"]["job_status"] == "VALIDATION"
    assert _queue(redis) == ["fin-idle", "run-idle"]
    assert mongo_db["check"].find_one()["locked"] is False


def test_a_job_out_of_retries_fails_instead_of_being_requeued(mongo_db, monkeypatch):
    redis, sio = _fake_backends(monkeypatch)
    stale = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=job_executor.MAX_IDLE_TIME + 60)
    mongo_db["eval_jobs"].insert_one(
        {
            "job_id": "stuck",
            "user_id": "alice",
            "job_status": "RUN",
            "alive_time": stale,
            "retry": job_executor.MAX_RETRY,
        }
    )

    check_for_idle_jobs_to_requeue(Database(), sleep=False)

    job = mongo_db["eval_jobs"].find_one({"job_id": "stuck"})
    assert job["job_status"] == "ERROR"
    assert str(job_executor.MAX_RETRY) in job["job_infos"]
    assert redis.llen("job_queue") == 0
    event, payload = sio.emit.call_args.args
    assert event == "job_status" and json.loads(payload)["status"] == "ERROR"
    assert mongo_db["check"].find_one()["locked"] is False


def test_ignored_job_goes_back_to_validation(mongo_db, monkeypatch):
    redis, sio = _fake_backends(monkeypatch)
    mongo_db["eval_jobs"].insert_one({"job_id": "ign", "user_id": "alice", "job_status": "IGNORED"})

    check_for_idle_jobs_to_requeue(Database(), sleep=False)

    assert mongo_db["eval_jobs"].find_one({"job_id": "ign"})["job_status"] == "VALIDATION"
    event, payload = sio.emit.call_args.args
    assert event == "job_status"
    assert json.loads(payload) == {"user_id": "alice", "job_id": "ign", "status": "VALIDATION"}
    assert redis.llen("job_queue") == 0


def test_nothing_to_do_leaves_the_queue_alone(mongo_db, monkeypatch):
    redis, sio = _fake_backends(monkeypatch)
    mongo_db["eval_jobs"].insert_one(
        {"job_id": "live", "user_id": "alice", "job_status": "RUN", "alive_time": dt.datetime.now(dt.UTC)}
    )
    check_for_idle_jobs_to_requeue(Database(), sleep=False)
    assert redis.llen("job_queue") == 0
    assert not sio.emit.called
    assert mongo_db["check"].find_one()["locked"] is False


# ------------------------------------------------------- idle sweep lock (X16)


def test_a_pod_that_did_not_get_the_lock_leaves_it_alone(mongo_db, monkeypatch):
    # the finally used to unlock unconditionally, so the pod that lost the race
    # released the holder's lock and two executors swept concurrently
    _fake_backends(monkeypatch)
    mongo_db["check"].insert_one({"locked": True})

    check_for_idle_jobs_to_requeue(Database(), sleep=False)

    assert mongo_db["check"].find_one()["locked"] is True


# --------------------------------------------------- template boxes (X11)


def test_template_boxes_fall_back_to_the_defaults(monkeypatch):
    from process_copy.config import DEFAULT_GRADE_BOX, DEFAULT_MATRICULE_BOX

    job_executor.apply_template_boxes([0.1, 0.9, 0.6, 0.9], [0.2, 0.8, 0.1, 0.3], None)
    assert job_executor.grade_box["exam"]["grade"] == (0.1, 0.9, 0.6, 0.9)
    assert job_executor.matricule_box["exam"]["front"] == (0.2, 0.8, 0.1, 0.3)
    assert job_executor.matricule_box["exam"]["regular"] == DEFAULT_MATRICULE_BOX["exam"]["regular"]

    # the next job has no boxes: it must not inherit the previous job's
    job_executor.apply_template_boxes(None, None, None)
    assert job_executor.grade_box["exam"]["grade"] == DEFAULT_GRADE_BOX["exam"]["grade"]
    assert job_executor.matricule_box["exam"]["front"] == DEFAULT_MATRICULE_BOX["exam"]["front"]


# ------------------------------------------------------------ job ids (X20)


def test_job_ids_from_the_queue_must_look_like_ids():
    assert job_executor.valid_job_id("6667a9b4-21b8-4450-ab6c-1e9e89537e38")
    assert job_executor.valid_job_id("template_12")
    for bad in ("../etc", "a/b", "", None, 12, "x" * 65, "-leading", "sp ace"):
        assert not job_executor.valid_job_id(bad), bad
