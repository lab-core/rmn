"""Validation of the per-question lists sent to ``/evaluate``.

A question with 0 page and 0 point is *ignored*: the template has a box for it
but the exam does not use it. Any other 0 or negative value is refused.
"""

import io
import json

import pytest

from utils.utils import validate_questions


def _evaluate(client, user, token, pages, points, bonus=None):
    keys = [k for k, _ in pages]
    if bonus is None:
        bonus = [[k, False] for k in keys]
    data = {
        "user_id": user,
        "token": token,
        "front_template_id": "front",
        "regular_template_id": "regular",
        "front_template_name": "front",
        "regular_template_name": "regular",
        "job_name": "exam",
        "statistics_for_students": "true",
        "n_pages_per_question": json.dumps(pages),
        "n_max_points_per_question": json.dumps(points),
        "bonus_enabled_map": json.dumps(bonus),
        "notes_csv_file": (io.BytesIO(b"Matricule,Nom complet\n"), "notes.csv"),
        "zip_file": (io.BytesIO(b"PK\x05\x06" + b"\x00" * 18), "copies.zip"),
    }
    return client.post("/evaluate", data=data, content_type="multipart/form-data")


def test_ignored_question_is_stored_as_zero(
    client, user_factory, login, app_module_fixture
):
    user_factory("alice")
    token = login("alice")
    pages = [["Q1", 2], ["Q2", 1], ["Q3", 0]]
    points = [["Q1", 10], ["Q2", 5], ["Q3", 0]]

    resp = _evaluate(client, "alice", token, pages, points)

    assert resp.status_code == 200, resp.data
    job = app_module_fixture.mongo["RMN"]["eval_jobs"].find_one({"user_id": "alice"})
    assert job["n_pages_per_question"] == pages
    assert job["n_max_points_per_question"] == points


@pytest.mark.parametrize(
    "pages,points",
    [
        ([["Q1", 0]], [["Q1", 5]]),  # ignored question with points
        ([["Q1", 2]], [["Q1", 0]]),  # graded question without point
        ([["Q1", -1]], [["Q1", 5]]),  # negative pages
        ([["Q1", 1.5]], [["Q1", 5]]),  # fractional pages
        ([["Q1", 2]], [["Q1", -5]]),  # negative points
        ([["Q1", 2], ["Q2", 1]], [["Q1", 5]]),  # different key sets
        ([["Q1", 2], ["Q1", 1]], [["Q1", 5], ["Q1", 5]]),  # duplicated key
    ],
)
def test_invalid_questions_are_rejected(client, user_factory, login, pages, points):
    user_factory("alice")
    token = login("alice")

    resp = _evaluate(client, "alice", token, pages, points)

    assert resp.status_code == 400, resp.data
    assert resp.get_json(force=True)["response"].startswith("Error:")


@pytest.mark.parametrize("key", ["q1", "Q0", "Q", "1", "Q1/..", "Q 1", "Q01"])
def test_question_keys_must_be_Qn(key):
    assert validate_questions([[key, 1]], [[key, 1]], [[key, False]]) is not None


def test_bonus_must_be_boolean():
    assert validate_questions([["Q1", 1]], [["Q1", 1]], [["Q1", "true"]]) is not None
    assert validate_questions([["Q1", 1]], [["Q1", 1]], [["Q1", 1]]) is not None
    assert validate_questions([["Q1", 1]], [["Q1", 1]], [["Q1", True]]) is None


def test_no_question_is_valid():
    assert validate_questions([], [], []) is None


def test_malformed_lists_are_rejected():
    assert validate_questions({"Q1": 1}, [], []) is not None
    assert validate_questions([["Q1"]], [["Q1", 1]], [["Q1", False]]) is not None
    assert validate_questions([["Q1", True]], [["Q1", 1]], [["Q1", False]]) is not None
