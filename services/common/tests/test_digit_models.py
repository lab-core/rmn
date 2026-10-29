import json
import os

import pytest

from rmn_common import digit_models
from rmn_common.storage import Storage

RUN = "0123456789abcdef0123456789abcdef"


def _model(storage, run_id=RUN):
    path = storage.abs_path(digit_models.model_path(run_id))
    os.makedirs(os.path.dirname(path))
    with open(path, "wb") as f:
        f.write(b"tflite")
    return path


def test_the_shipped_model_runs_until_one_is_activated(tmp_path):
    storage = Storage(tmp_path)
    assert digit_models.active_model(storage) is None

    path = _model(storage)
    digit_models.set_active_model(storage, RUN, "admin")

    active = digit_models.active_model(storage)
    assert active["run_id"] == RUN and active["activated_by"] == "admin"
    assert active["path"] == path

    digit_models.set_active_model(storage, None, "admin")
    assert digit_models.active_model(storage) is None
    # going back twice is not an error
    digit_models.set_active_model(storage, None, "admin")


def test_a_run_without_a_model_cannot_be_activated(tmp_path):
    storage = Storage(tmp_path)
    with pytest.raises(ValueError):
        digit_models.set_active_model(storage, RUN, "admin")
    assert digit_models.active_model(storage) is None


@pytest.mark.parametrize(
    "pointer",
    ["not json", json.dumps({"run_id": "../../etc"}), json.dumps({"other": 1}), "[]"],
)
def test_a_broken_pointer_is_the_shipped_model(tmp_path, pointer):
    storage = Storage(tmp_path)
    _model(storage)
    path = storage.abs_path(digit_models.ACTIVE_FILE)
    with open(path, "w") as f:
        f.write(pointer)
    assert digit_models.active_model(storage) is None


def test_a_pointer_to_a_deleted_model_is_the_shipped_model(tmp_path):
    storage = Storage(tmp_path)
    path = _model(storage)
    digit_models.set_active_model(storage, RUN, "admin")
    os.remove(path)
    assert digit_models.active_model(storage) is None


@pytest.mark.parametrize("run_id", ["", "abc", "../x", RUN.upper(), None, 3])
def test_only_server_run_ids_name_a_path(run_id):
    assert not digit_models.valid_run_id(run_id)
    with pytest.raises(ValueError):
        digit_models.model_path(run_id)
