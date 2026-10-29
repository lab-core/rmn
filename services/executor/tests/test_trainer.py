"""The trainer worker: a run taken off the queue, done, and written back.

Training needs TensorFlow, which only the trainer image installs
(requirements-train.txt): those tests are skipped without it. The
evaluation runs on LiteRT and is tested everywhere.
"""

import numpy as np
import pytest

import trainer
from process_copy import retrain
from process_copy.imaging import storage
from rmn_common import digit_models
from rmn_common.status import Digit_Model_Status as Status

RUN = "cd" * 16


@pytest.fixture(autouse=True)
def small_mnist(monkeypatch, printed):
    """A few printed digits instead of MNIST: no download, a quick epoch."""
    x = retrain.framed(
        np.stack([printed(d, v) for v in range(3) for d in range(10)]), [0.2]
    )
    y = np.tile(np.arange(10), 3)
    monkeypatch.setattr(retrain, "mnist", lambda: ((x, y), (x, y)))
    monkeypatch.setattr(retrain, "EPOCHS", 1)
    monkeypatch.setattr(retrain, "AUGMENTED", 1)


def queue(mongo_db, action, run_id=RUN):
    mongo_db[digit_models.COLLECTION].insert_one(
        {"run_id": run_id, "action": action, "status": Status.QUEUED.value}
    )


def row(mongo_db, run_id=RUN):
    return mongo_db[digit_models.COLLECTION].find_one({"run_id": run_id})


def test_an_evaluation_scores_the_model_in_use(mongo_db, fill_bank):
    fill_bank(n_copies=10)
    queue(mongo_db, digit_models.EVALUATE)

    trainer.process(mongo_db, storage, RUN)

    done = row(mongo_db)
    assert done["status"] == Status.DONE.value, done.get("error")
    assert done["model"] is None, "the shipped model"
    assert done["bank"]["samples"] == 100
    scores = done["results"]["model"]
    assert scores["bank"]["n"] == 100
    assert scores["test"]["n"] == done["bank"]["test"]
    assert scores["mnist"]["n"] == 30


def test_a_run_is_taken_once(mongo_db):
    queue(mongo_db, digit_models.EVALUATE)
    mongo_db[digit_models.COLLECTION].update_one(
        {"run_id": RUN}, {"$set": {"status": Status.RUNNING.value}}
    )
    trainer.process(mongo_db, storage, RUN)
    assert row(mongo_db)["status"] == Status.RUNNING.value
    trainer.process(mongo_db, storage, "ef" * 16)  # unknown: nothing happens


def test_a_bank_too_small_is_refused_with_a_reason(mongo_db, fill_bank):
    fill_bank(n_copies=1)
    queue(mongo_db, digit_models.TRAIN)

    trainer.process(mongo_db, storage, RUN)

    failed = row(mongo_db)
    assert failed["status"] == Status.ERROR.value
    assert "trop petite" in failed["error"]
    assert failed["finished"] is not None


def test_training_writes_a_model_scored_beside_the_one_in_use(
    mongo_db, storage_root, fill_bank
):
    pytest.importorskip("tensorflow")
    fill_bank(n_copies=10)
    queue(mongo_db, digit_models.TRAIN)

    trainer.process(mongo_db, storage, RUN)

    done = row(mongo_db)
    assert done["status"] == Status.DONE.value, done.get("error")
    assert done["progress"]["epoch"] == done["progress"]["epochs"] == 1
    candidate, current = done["results"]["candidate"], done["results"]["current"]
    assert candidate["test"]["n"] == current["test"]["n"] == done["bank"]["test"] > 0
    assert current["model"] is None
    # written, but not activated: the admin decides
    assert (storage_root / digit_models.model_path(RUN)).is_file()
    assert digit_models.active_model(storage) is None

    digit_models.set_active_model(storage, RUN, "admin")
    from process_copy.classifier import load_classifier

    assert load_classifier().predict(np.zeros((2, 28, 28, 1))).shape == (2, 10)


def test_the_training_set_mixes_the_framed_bank_with_mnist(fill_bank, monkeypatch):
    """Without TensorFlow: what fine_tune is given."""
    from process_copy import bank_eval
    from process_copy.config import digit_margins

    fill_bank(n_copies=2)
    bank = bank_eval.load_bank()
    monkeypatch.setattr(retrain, "MNIST_REPLAY", 7)
    replay = (np.zeros((50, 28, 28), dtype="uint8"), np.full(50, 3))

    x, y = retrain.training_set(bank, replay)

    framings = len(bank) * len(digit_margins)
    assert x.shape == ((retrain.AUGMENTED + 1) * framings + 7, 28, 28)
    assert x.dtype == np.uint8 and len(y) == len(x)
    # every bank digit is there once per framing and per distortion
    assert (y == 0).sum() == 2 * len(digit_margins) * (retrain.AUGMENTED + 1)
    # the order is shuffled, but the same on every run
    assert np.array_equal(retrain.training_set(bank, replay)[1], y)
    # an empty bank gives MNIST only
    empty = bank_eval.Bank(bank.x[:0], bank.y[:0])
    assert retrain.training_set(empty, replay)[0].shape == (7, 28, 28)
