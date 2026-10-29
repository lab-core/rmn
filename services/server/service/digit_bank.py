"""The digit bank and the digit model, as the admin page shows and drives them.

The bank is written by the executor (``process_copy.digit_bank``) and read
here from the shared storage; the runs that retrain or score the model are
rows of ``digit_models`` that the trainer worker takes from ``train_queue``
(:mod:`rmn_common.digit_models`).
"""

import datetime as dt
import json
import os
import uuid

from rmn_common import digit_models
from rmn_common.status import Digit_Model_Status as Status

# the runs listed on the admin page, newest first
RUNS_SHOWN = 10
# a run nobody took in that long will not be: the trainer is not deployed, or
# its pod cannot be scheduled
QUEUED_TOO_LONG = dt.timedelta(hours=2)
UNFINISHED = (Status.QUEUED.value, Status.RUNNING.value)


def _utc(value):
    """Mongo hands back naive datetimes; they are UTC."""
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def _iso(value):
    return _utc(value).isoformat() if isinstance(value, dt.datetime) else value


def _counter():
    return {"n": 0, "read": 0, "correct": 0}


def _count(entry, read, label):
    entry["n"] += 1
    if read is not None:
        entry["read"] += 1
        entry["correct"] += int(read == label)


def bank_summary(storage):
    """What the bank holds, and how well the recogniser read it at the time.

    The samples are counted from the files, by digit; the index tells where
    they come from and what the model in use then read (``read``), which
    gives the reading accuracy without running any model.

    Returns:
        ``{"samples", "bytes", "per_digit": [{"n", "read", "correct"}] * 10,
        "per_kind": {kind: {"n", "read", "correct"}}, "reading": {"n", "read",
        "correct"}, "jobs", "copies", "first", "last", "staged": {"jobs",
        "readings"}}``.
    """
    files = [0] * 10
    size = 0
    root = storage.abs_path(digit_models.SAMPLES_DIR)
    for label in range(10):
        directory = os.path.join(root, str(label))
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.name.endswith(".png") and entry.is_file():
                        files[label] += 1
                        size += entry.stat().st_size
        except FileNotFoundError:
            continue

    per_digit = [_counter() for _ in range(10)]
    per_kind = {}
    reading = _counter()
    jobs, copies = set(), set()
    first = last = None
    try:
        with open(storage.abs_path(digit_models.INDEX_FILE)) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    label = int(entry["label"])
                except (ValueError, KeyError, TypeError):
                    continue
                if not 0 <= label <= 9:
                    continue
                read = entry.get("read") if isinstance(entry.get("read"), int) else None
                _count(per_digit[label], read, label)
                _count(
                    per_kind.setdefault(entry.get("kind") or "unknown", _counter()),
                    read,
                    label,
                )
                _count(reading, read, label)
                if entry.get("job_id"):
                    jobs.add(entry["job_id"])
                    copies.add((entry["job_id"], entry.get("document_index")))
                read_at = entry.get("read_at")
                if isinstance(read_at, str):
                    first = min(first or read_at, read_at)
                    last = max(last or read_at, read_at)
    except FileNotFoundError:
        pass
    for label in range(10):
        # the files are the bank; the index only describes them
        per_digit[label]["n"] = files[label]

    staged_jobs = staged_readings = 0
    try:
        with os.scandir(storage.abs_path(digit_models.STAGED_DIR)) as entries:
            for job in entries:
                if not job.is_dir():
                    continue
                staged_jobs += 1
                for _directory, _dirs, names in os.walk(job.path):
                    staged_readings += sum(name.endswith(".npz") for name in names)
    except FileNotFoundError:
        pass

    return {
        "samples": sum(files),
        "bytes": size,
        "per_digit": per_digit,
        "per_kind": per_kind,
        "reading": reading,
        "jobs": len(jobs),
        "copies": len(copies),
        "first": first,
        "last": last,
        "staged": {"jobs": staged_jobs, "readings": staged_readings},
    }


def close_dead_runs(collection, now=None):
    """Close the runs no trainer will ever finish, so a new one can start.

    A running run whose worker stopped writing died with its pod (deadline,
    eviction); a queued one nobody took in :data:`QUEUED_TOO_LONG` is waiting
    for a worker that is not there.
    """
    now = now or dt.datetime.now(dt.UTC)
    stale = now - dt.timedelta(seconds=digit_models.STALE_AFTER_SECONDS)
    for row in collection.find({"status": {"$in": list(UNFINISHED)}}):
        if row["status"] == Status.RUNNING.value:
            alive = row.get("alive_time") or row.get("started") or row.get("created")
            dead = alive is None or _utc(alive) < stale
            reason = "Le worker d'entraînement s'est arrêté avant la fin."
        else:
            created = row.get("created")
            dead = created is None or _utc(created) < now - QUEUED_TOO_LONG
            reason = "Aucun worker d'entraînement n'a pris la demande."
        if dead:
            collection.update_one(
                {"_id": row["_id"], "status": row["status"]},
                {
                    "$set": {
                        "status": Status.ERROR.value,
                        "error": reason,
                        "finished": now,
                    }
                },
            )


def runs(collection, limit=RUNS_SHOWN):
    """The latest runs, newest first, ready for JSON."""
    close_dead_runs(collection)
    rows = []
    for row in collection.find({}, {"_id": 0}).sort("created", -1).limit(limit):
        rows.append({key: _iso(value) for key, value in row.items()})
    return rows


def overview(db, storage):
    """Everything the admin page shows of the bank and the model."""
    active = digit_models.active_model(storage)
    if active is not None:
        active.pop("path")
    return {
        "bank": bank_summary(storage),
        "active": active,
        "runs": runs(db[digit_models.COLLECTION]),
    }


def start_run(db, redis, action, user_id):
    """Queue a run for the trainer worker.

    Returns:
        The new row, or None when a run is still queued or running: one run
        at a time, the trainer is a single worker.

    Raises:
        ValueError: If ``action`` is not a run action.
    """
    if action not in digit_models.ACTIONS:
        raise ValueError(action)
    collection = db[digit_models.COLLECTION]
    close_dead_runs(collection)
    if collection.find_one({"status": {"$in": list(UNFINISHED)}}):
        return None
    row = {
        "run_id": uuid.uuid4().hex,
        "action": action,
        "status": Status.QUEUED.value,
        "requested_by": user_id,
        "created": dt.datetime.now(dt.UTC),
    }
    collection.insert_one(dict(row))
    redis.rpush(digit_models.TRAIN_QUEUE, json.dumps({"run_id": row["run_id"]}))
    return {key: _iso(value) for key, value in row.items()}


def activate(db, storage, run_id, user_id):
    """Make the executors run the model of ``run_id``, or the shipped one.

    Args:
        run_id: A finished training run, or ``""`` for the shipped model.

    Raises:
        ValueError: With the reason, when the run cannot be activated.
    """
    if run_id:
        row = db[digit_models.COLLECTION].find_one({"run_id": run_id})
        if (
            row is None
            or row.get("action") != digit_models.TRAIN
            or row.get("status") != Status.DONE.value
        ):
            raise ValueError("Seul un entraînement terminé peut être activé.")
    digit_models.set_active_model(storage, run_id or None, user_id)
