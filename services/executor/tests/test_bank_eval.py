"""Scoring a digit model on the digit bank, and the bank's train/test split."""

import json

import numpy as np

from process_copy import bank_eval, digit_bank
from process_copy.classifier import SHIPPED_MODEL, load_classifier, model_in_use
from process_copy.imaging import storage
from rmn_common import digit_models


# ------------------------------------------------------------- the split --
def test_a_copy_is_on_one_side_of_the_split_only():
    metas = [
        {"job_id": f"j{j}", "document_index": d} for j in range(40) for d in range(5)
    ]
    sides = {}
    for meta in metas:
        key = (meta["job_id"], meta["document_index"])
        # every digit of the copy lands where its first one did
        for position in range(7):
            side = bank_eval.is_test(dict(meta, position=position, sha1=str(position)))
            assert sides.setdefault(key, side) == side
    share = sum(sides.values()) / len(sides)
    assert 0.1 < share < 0.3, "about one copy in five is kept for the test"


def test_a_sample_the_index_forgot_is_placed_by_its_pixels():
    assert bank_eval.is_test({"sha1": "a"}) == bank_eval.is_test({"sha1": "a"})
    assert len({bank_eval.is_test({"sha1": str(i)}) for i in range(50)}) == 2


# -------------------------------------------------------------- the bank --
def test_the_bank_is_loaded_with_its_index(fill_bank):
    fill_bank(n_copies=2)
    bank = bank_eval.load_bank()
    assert len(bank) == 20 and bank.x.shape == (20, 64, 64)
    assert sorted(bank.y.tolist()) == sorted(list(range(10)) * 2)
    assert all(m["kind"] == digit_bank.MATRICULE and "sha1" in m for m in bank.meta)

    train, test = bank.split()
    assert len(train) + len(test) == len(bank)


def test_an_empty_bank_scores_nothing():
    bank = bank_eval.load_bank()
    assert len(bank) == 0
    result = bank_eval.evaluate(load_classifier(SHIPPED_MODEL), bank)
    assert result["n"] == 0 and result["accuracy"] is None


def test_a_broken_index_line_is_skipped(storage_root, fill_bank):
    fill_bank(n_copies=1)
    with open(storage_root / digit_bank.INDEX_FILE, "a") as f:
        f.write("not json\n[]\n")
    assert len(bank_eval.read_index()) == 10


# ------------------------------------------------------------ the scores --
def test_the_shipped_model_reads_printed_digits(fill_bank):
    fill_bank(n_copies=3)
    result = bank_eval.evaluate(load_classifier(SHIPPED_MODEL), bank_eval.load_bank())
    assert result["n"] == 30
    assert result["accuracy"] >= 0.8
    assert sum(d["n"] for d in result["per_digit"]) == 30
    assert result["per_kind"][digit_bank.MATRICULE]["n"] == 30
    assert sum(map(sum, result["confusion"])) == 30
    json.dumps(result)  # stored in Mongo as is


def test_scores_count_per_digit_and_kind():
    result = bank_eval.scores(
        np.array([1, 1, 2, 3]),
        np.array([1, 7, 2, 8]),
        ["matricule", "matricule", "ink_grade", None],
    )
    assert result["correct"] == 2 and result["accuracy"] == 0.5
    assert result["per_digit"][1] == {"n": 2, "correct": 1}
    assert result["confusion"][1][7] == 1 and result["confusion"][3][8] == 1
    assert result["per_kind"] == {
        "matricule": {"n": 2, "correct": 1},
        "ink_grade": {"n": 1, "correct": 1},
        "unknown": {"n": 1, "correct": 0},
    }


# ------------------------------------------------------ the model in use --
def test_the_executors_run_the_model_an_admin_activated(storage_root):
    assert model_in_use() == (SHIPPED_MODEL, None)

    run_id = "ab" * 16
    path = storage_root / digit_models.model_path(run_id)
    path.parent.mkdir(parents=True)
    path.write_bytes(open(SHIPPED_MODEL, "rb").read())
    digit_models.set_active_model(storage, run_id, "admin")

    assert model_in_use() == (str(path), run_id)
    # and it loads
    assert load_classifier().predict(np.zeros((1, 28, 28, 1))).shape == (1, 10)

    path.unlink()
    assert model_in_use() == (
        SHIPPED_MODEL,
        None,
    ), "a vanished model is the shipped one"
