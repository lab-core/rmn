"""The trainer worker: retrain the digit model on the digit bank, or score it.

An Administrateur asks for a run from the admin page; the server writes it to
the ``digit_models`` collection and queues its id on ``train_queue``
(:mod:`rmn_common.digit_models`). This worker, in its own image because it
needs TensorFlow (``Dockerfile.trainer``), takes the run and:

- ``evaluate``: scores the model the executors run on the bank's test part,
  on the whole bank and on MNIST's test set;
- ``train``: fine-tunes the shipped model on the bank's training part
  (:mod:`process_copy.retrain`), writes it next to the bank, and scores it
  beside the model in use on the same test part.

A trained model is never activated here: the admin compares the scores and
activates it from the admin page.
"""

import datetime as dt
import json
import os
import sys
import tempfile
import threading
import traceback
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / "python"))

from rmn_common import digit_models  # noqa: E402
from rmn_common.status import Digit_Model_Status as Status  # noqa: E402
from runtime import MAX_IDLE_TIME, timestamped_print  # noqa: E402
from utils.clients import mongo_client, redis_client  # noqa: E402
from utils.storage import Storage  # noqa: E402

print = timestamped_print

# below this many training samples a run is refused: the scores of a model
# fine-tuned on a handful of digits say nothing
MIN_TRAIN_SAMPLES = 20
# how often a running run tells the server it is alive
# (digit_models.STALE_AFTER_SECONDS)
HEARTBEAT_SECONDS = 60


def now():
    return dt.datetime.now(dt.UTC)


class Run:
    """One row of ``digit_models``, written as the run goes."""

    def __init__(self, collection, run_id):
        self.collection = collection
        self.run_id = run_id
        self._stop = threading.Event()
        self._thread = None

    def claim(self):
        """Take the run if it is still queued; None when someone else has it."""
        return self.collection.find_one_and_update(
            {"run_id": self.run_id, "status": Status.QUEUED.value},
            {
                "$set": {
                    "status": Status.RUNNING.value,
                    "started": now(),
                    "alive_time": now(),
                }
            },
        )

    def set(self, **fields):
        self.collection.update_one(
            {"run_id": self.run_id}, {"$set": dict(fields, alive_time=now())}
        )

    def __enter__(self):
        def beat():
            while not self._stop.wait(HEARTBEAT_SECONDS):
                try:
                    self.set()
                except Exception as e:
                    print("Heartbeat failed:", e)

        self._thread = threading.Thread(target=beat, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        return False


def model_scores(classifier, test, bank, replay_test):
    """What the admin page shows of a model: test part, whole bank, MNIST."""
    from process_copy import bank_eval

    x_mnist, y_mnist = replay_test
    return {
        "test": bank_eval.evaluate(classifier, test),
        "bank": bank_eval.evaluate(classifier, bank),
        "mnist": bank_eval.evaluate_images(classifier, x_mnist, y_mnist),
    }


def evaluate(run, storage, target=None):
    """Score a model: the one the executors run, or the model a training wrote.

    Args:
        target: The training run whose model is scored; None for the model in
            use.
    """
    from process_copy import bank_eval, retrain
    from process_copy.classifier import DigitClassifier, load_classifier, model_in_use

    bank = bank_eval.load_bank(storage)
    train, test = bank.split()
    if target:
        path, model = storage.abs_path(digit_models.model_path(target)), target
        if not os.path.isfile(path):
            raise ValueError("Le modèle de cet entraînement n'existe plus.")
        classifier = DigitClassifier(path)
    else:
        path, model = model_in_use(storage)
        classifier = load_classifier(path)
    _, replay_test = retrain.mnist()
    run.set(
        model=model,
        bank={"samples": len(bank), "train": len(train), "test": len(test)},
    )
    print(f"Evaluating {model or 'the shipped model'} on {len(bank)} samples")
    scores = model_scores(classifier, test, bank, replay_test)
    return {"model": dict(scores, model=model)}


def train(run, storage, work_dir):
    """Fine-tune the shipped model on the bank's training part, then score it."""
    from process_copy import bank_eval, retrain
    from process_copy.classifier import DigitClassifier, load_classifier, model_in_use

    bank = bank_eval.load_bank(storage)
    train_part, test = bank.split()
    run.set(bank={"samples": len(bank), "train": len(train_part), "test": len(test)})
    if len(train_part) < MIN_TRAIN_SAMPLES or not len(test):
        raise ValueError(
            f"La banque est trop petite pour entraîner un modèle : {len(train_part)} "
            f"chiffre(s) d'entraînement (minimum {MIN_TRAIN_SAMPLES}) et "
            f"{len(test)} de test."
        )

    (x_mnist, y_mnist), replay_test = retrain.mnist()
    x, y = retrain.training_set(train_part, (x_mnist, y_mnist))
    print(f"Training on {len(train_part)} bank samples ({len(y)} images with MNIST)")

    def progress(epoch, epochs, logs):
        run.set(
            progress={
                "epoch": epoch,
                "epochs": epochs,
                "loss": logs.get("loss"),
                "accuracy": logs.get("accuracy"),
            }
        )

    model = retrain.fine_tune(
        str(ROOT_DIR / "digit_recognizer.h5"), x, y, on_epoch=progress
    )
    local = work_dir / digit_models.MODEL_FILE
    local.write_bytes(retrain.convert(model))

    # scored before it is stored: a model that cannot be loaded never lands
    candidate = model_scores(DigitClassifier(local), test, bank, replay_test)
    path, current_model = model_in_use(storage)
    current = model_scores(load_classifier(path), test, bank, replay_test)
    storage.move_to(str(local), digit_models.model_path(run.run_id))
    return {
        "candidate": dict(candidate, model=run.run_id),
        "current": dict(current, model=current_model),
    }


def process(db, storage, run_id):
    """Run the run ``run_id`` if it is still waiting."""
    run = Run(db[digit_models.COLLECTION], run_id)
    row = run.claim()
    if row is None:
        print(f"Run {run_id} is not waiting any more")
        return
    action = row.get("action")
    print(f"Run {run_id}: {action}")
    with run, tempfile.TemporaryDirectory(prefix="train_") as work:
        try:
            if action == digit_models.TRAIN:
                results = train(run, storage, Path(work))
            elif action == digit_models.EVALUATE:
                results = evaluate(run, storage, row.get("target"))
            else:
                raise ValueError(f"unknown action {action!r}")
            run.set(status=Status.DONE.value, finished=now(), results=results)
            print(f"Run {run_id} done")
        except Exception as e:
            traceback.print_exc()
            run.set(status=Status.ERROR.value, finished=now(), error=str(e))


if __name__ == "__main__":
    mongo = mongo_client()
    db = mongo["RMN"]
    redis = redis_client()
    storage = Storage()
    # as the executor: one item per pod under KEDA, a loop in development
    blocking = (
        os.getenv("REDIS_POP") == "block" or os.getenv("ENVIRONMENT") != "production"
    )
    try:
        while True:
            if blocking:
                item = redis.blpop(digit_models.TRAIN_QUEUE, timeout=MAX_IDLE_TIME)
                item = item[1] if item else None
            else:
                item = redis.lpop(digit_models.TRAIN_QUEUE)
            if item:
                try:
                    run_id = json.loads(item).get("run_id")
                except (ValueError, AttributeError):
                    run_id = None
                if digit_models.valid_run_id(run_id):
                    process(db, storage, run_id)
                else:
                    print(f"Refusing a run with an invalid id: {item!r}")
            if not blocking:
                break
    finally:
        mongo.close()
    print("Trainer end.")
