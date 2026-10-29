"""The digit bank on the admin page: what it holds, and the trainer's runs."""

import datetime as dt
import json

import pytest
from rmn_common import digit_models

from service import digit_bank

ADMIN = "Administrateur"
MANAGER = "Gestionnaire"
RUN = "ab" * 16


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def db(app_module_fixture):
    return app_module_fixture.mongo["RMN"]


@pytest.fixture
def admin(user_factory, login):
    user_factory("root", role=ADMIN)
    return login("root")


def _post(client, path, token, **data):
    return client.post(path, data={"user_id": "root", **data}, headers=_auth(token))


def _get(client, token):
    resp = client.get("/manage/digit-bank", headers=_auth(token))
    assert resp.status_code == 200
    return resp.get_json(force=True)["response"]


def _sample(root, label, name, **meta):
    path = root / digit_models.SAMPLES_DIR / str(label) / f"{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"png")
    index = root / digit_models.INDEX_FILE
    with open(index, "a") as f:
        f.write(json.dumps(dict(meta, sha1=name, label=label)) + "\n")


def test_the_bank_is_counted_with_what_the_model_read_then(client, admin, storage_root):
    _sample(
        storage_root,
        1,
        "a",
        kind="matricule",
        job_id="j1",
        document_index=0,
        read=1,
        read_at="2026-10-01T10:00:00+00:00",
    )
    _sample(
        storage_root,
        1,
        "b",
        kind="matricule",
        job_id="j1",
        document_index=0,
        read=7,
        read_at="2026-10-02T10:00:00+00:00",
    )
    _sample(
        storage_root,
        3,
        "c",
        kind="ink_grade",
        job_id="j2",
        document_index=4,
        read=None,
        read_at="2026-09-30T10:00:00+00:00",
    )
    with open(storage_root / digit_models.INDEX_FILE, "a") as f:
        f.write("broken\n")
    staged = storage_root / digit_models.STAGED_DIR / "j3" / "0"
    staged.mkdir(parents=True)
    (staged / "r1.npz").write_bytes(b"x")
    (staged / "r2.npz").write_bytes(b"x")

    bank = _get(client, admin)["bank"]

    assert bank["samples"] == 3 and bank["bytes"] == 9
    assert bank["per_digit"][1] == {"n": 2, "read": 2, "correct": 1}
    assert bank["per_digit"][3] == {"n": 1, "read": 0, "correct": 0}
    assert bank["per_kind"]["matricule"] == {"n": 2, "read": 2, "correct": 1}
    assert bank["reading"] == {"n": 3, "read": 2, "correct": 1}
    assert bank["jobs"] == 2 and bank["copies"] == 2
    assert bank["first"].startswith("2026-09-30") and bank["last"].startswith(
        "2026-10-02"
    )
    assert bank["staged"] == {"jobs": 1, "readings": 2}


def test_an_empty_bank(client, admin, storage_root):
    overview = _get(client, admin)
    assert overview["bank"]["samples"] == 0 and overview["bank"]["reading"]["read"] == 0
    assert overview["active"] is None and overview["runs"] == []


def test_a_run_is_queued_for_the_trainer_one_at_a_time(
    client, admin, db, app_module_fixture
):
    resp = _post(client, "/manage/digit-bank/run", admin, action="train")
    assert resp.status_code == 200
    row = resp.get_json(force=True)["response"]
    assert row["status"] == "QUEUED" and row["action"] == "train"
    assert digit_models.valid_run_id(row["run_id"])
    queued = app_module_fixture.redis.lpop(digit_models.TRAIN_QUEUE)
    assert json.loads(queued) == {"run_id": row["run_id"]}

    assert (
        _post(client, "/manage/digit-bank/run", admin, action="evaluate").status_code
        == 409
    )
    assert (
        _post(client, "/manage/digit-bank/run", admin, action="delete").status_code
        == 400
    )

    db[digit_models.COLLECTION].update_one(
        {"run_id": row["run_id"]}, {"$set": {"status": "DONE"}}
    )
    assert (
        _post(client, "/manage/digit-bank/run", admin, action="evaluate").status_code
        == 200
    )
    runs = _get(client, admin)["runs"]
    assert [r["action"] for r in runs] == ["evaluate", "train"]


def test_a_dead_run_does_not_block_the_next_one(db):
    collection = db[digit_models.COLLECTION]
    now = dt.datetime.now(dt.UTC)
    collection.insert_many(
        [
            {
                "run_id": "1" * 32,
                "status": "RUNNING",
                "alive_time": now - dt.timedelta(hours=1),
            },
            {
                "run_id": "2" * 32,
                "status": "RUNNING",
                "alive_time": now - dt.timedelta(minutes=1),
            },
            {
                "run_id": "3" * 32,
                "status": "QUEUED",
                "created": now - dt.timedelta(hours=3),
            },
            {
                "run_id": "4" * 32,
                "status": "QUEUED",
                "created": now - dt.timedelta(minutes=5),
            },
        ]
    )

    digit_bank.close_dead_runs(collection, now)

    status = {r["run_id"][0]: r["status"] for r in collection.find()}
    assert status == {"1": "ERROR", "2": "RUNNING", "3": "ERROR", "4": "QUEUED"}
    assert "arrêté" in collection.find_one({"run_id": "1" * 32})["error"]


def test_only_a_finished_training_is_activated(client, admin, db, storage_root):
    collection = db[digit_models.COLLECTION]
    collection.insert_one({"run_id": RUN, "action": "train", "status": "RUNNING"})
    assert (
        _post(client, "/manage/digit-bank/activate", admin, run_id=RUN).status_code
        == 400
    )

    collection.update_one({"run_id": RUN}, {"$set": {"status": "DONE"}})
    # done, but its model is gone
    assert (
        _post(client, "/manage/digit-bank/activate", admin, run_id=RUN).status_code
        == 400
    )

    model = storage_root / digit_models.model_path(RUN)
    model.parent.mkdir(parents=True)
    model.write_bytes(b"tflite")
    resp = _post(client, "/manage/digit-bank/activate", admin, run_id=RUN)
    assert resp.status_code == 200
    active = resp.get_json(force=True)["response"]["active"]
    assert active["run_id"] == RUN and active["activated_by"] == "root"
    assert "path" not in active

    assert (
        _post(client, "/manage/digit-bank/activate", admin, run_id="").status_code
        == 200
    )
    assert _get(client, admin)["active"] is None

    assert (
        _post(client, "/manage/digit-bank/activate", admin, run_id="../x").status_code
        == 400
    )


def test_an_admin_s_only(client, user_factory, login):
    user_factory("chef", role=MANAGER)
    token = login("chef")
    assert client.get("/manage/digit-bank", headers=_auth(token)).status_code == 403
    for path, data in (("run", {"action": "train"}), ("activate", {"run_id": ""})):
        resp = client.post(
            f"/manage/digit-bank/{path}",
            data={"user_id": "chef", **data},
            headers=_auth(token),
        )
        assert resp.status_code == 403
