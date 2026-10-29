"""The digit model the recogniser runs, and the runs that retrain or evaluate it.

The executor image ships a model (``digit_recognizer.tflite``). From the admin
page an Administrateur can have it retrained on the digit bank: the server
queues a run on :data:`TRAIN_QUEUE`, the trainer worker
(``services/executor/trainer.py``) fine-tunes the shipped model and writes the
result under :data:`MODELS_DIR`, and the admin activates it once its scores
show it reads the bank better. Nothing is activated on its own.

The active model is named by a file in the storage, not by a database row:
the recogniser loads its model deep inside the reading code, where there is a
storage but no database handle.
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# the queue the trainer worker pops, apart from the executors' job_queue: the
# trainer image carries TensorFlow, the executor image does not
TRAIN_QUEUE = "train_queue"
# one row per run, train or evaluate
COLLECTION = "digit_models"
TRAIN = "train"
EVALUATE = "evaluate"
ACTIONS = (TRAIN, EVALUATE)

# The digit bank's layout (written by the executor's process_copy.digit_bank,
# read by the server for the admin page): staged crops per job, labelled
# samples per digit, and an index line per sample.
BANK_DIR = "digit_bank"
STAGED_DIR = os.path.join(BANK_DIR, "staged")
SAMPLES_DIR = os.path.join(BANK_DIR, "samples")
INDEX_FILE = os.path.join(BANK_DIR, "index.jsonl")
# beside the samples, and like them out of reach of every sweep
# (rmn_common.storage.CORPUS_DIRS)
MODELS_DIR = os.path.join(BANK_DIR, "models")
ACTIVE_FILE = os.path.join(MODELS_DIR, "active.json")
MODEL_FILE = "digit_recognizer.tflite"

# a run is named by the server (uuid4 hex); anything else never becomes a path
RUN_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
# a running run whose worker has not written for this long is dead: its pod
# hit the deadline or was evicted, and nothing else will ever close it
STALE_AFTER_SECONDS = 15 * 60


def valid_run_id(run_id: Any) -> bool:
    """Whether ``run_id`` has the shape of a run the server created."""
    return isinstance(run_id, str) and RUN_ID_PATTERN.fullmatch(run_id) is not None


def model_path(run_id: str) -> str:
    """Storage-relative path of the model a training run wrote.

    Raises:
        ValueError: If ``run_id`` is not a run id.
    """
    if not valid_run_id(run_id):
        raise ValueError(f"not a run id: {run_id!r}")
    return os.path.join(MODELS_DIR, run_id, MODEL_FILE)


def active_model(storage: Any) -> Optional[Dict[str, Any]]:
    """The trained model the executors run, or None for the shipped one.

    A pointer that cannot be read, or that names a model whose file is gone,
    is the shipped model: a broken pointer must never stop the reading.

    Args:
        storage: A :class:`rmn_common.storage.Storage`.

    Returns:
        ``{"run_id", "activated_at", "activated_by", "path"}`` with ``path``
        absolute, or None.
    """
    try:
        with open(storage.abs_path(ACTIVE_FILE)) as f:
            pointer = json.load(f)
        path = storage.abs_path(model_path(pointer["run_id"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not os.path.isfile(path):
        return None
    return dict(pointer, path=path)


def set_active_model(storage: Any, run_id: Optional[str], user: str) -> None:
    """Make the model of ``run_id`` the one the executors run.

    Args:
        storage: A :class:`rmn_common.storage.Storage`.
        run_id: A training run whose model exists, or None to go back to the
            shipped model.
        user: Who made the change, kept in the pointer.

    Raises:
        ValueError: If the run has no model file.
    """
    pointer_path = storage.abs_path(ACTIVE_FILE)
    if not run_id:
        try:
            os.remove(pointer_path)
        except FileNotFoundError:
            pass
        return
    if not os.path.isfile(storage.abs_path(model_path(run_id))):
        raise ValueError(f"run {run_id} has no model")
    pointer = {
        "run_id": run_id,
        "activated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "activated_by": user,
    }
    os.makedirs(os.path.dirname(pointer_path), exist_ok=True)
    # an executor starting mid-write reads either pointer whole, never half
    tmp = pointer_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(pointer, f)
    os.replace(tmp, pointer_path)
