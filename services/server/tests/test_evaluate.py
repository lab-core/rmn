"""Validation of the per-question lists sent to ``/evaluate``.

A question with 0 page and 0 point is *ignored*: the template has a box for it
but the exam does not use it. Any other 0 or negative value is refused.
"""

import io
import json
import os
import shutil

import pytest

from rmn_common.questions import validate_questions


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
    return client.post("/jobs/evaluate", data=data, content_type="multipart/form-data")


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


def test_bonus_update_is_validated(client, user_factory, login, job_factory, app_module_fixture):
    # the executor reads bonus_enabled_map back: garbage used to be stored as is
    user_factory("alice")
    token = login("alice")
    job_factory("j1", "alice")
    base = {"job_id": "j1", "user_id": "alice", "token": token}
    for bad in ('"garbage"', '[["bonus", true]]', '[["Q1", "yes"]]', '[["Q1", true], ["Q1", false]]', "{not json"):
        assert client.post("/jobs/update/bonus", data={**base, "bonus_enabled_map": bad}).status_code == 400, bad
    assert client.post("/jobs/update/bonus", data={**base, "bonus_enabled_map": '[["Q1", true], ["Q2", false]]'}).status_code == 200
    job = app_module_fixture.mongo["RMN"]["eval_jobs"].find_one({"job_id": "j1"})
    assert job["bonus_enabled_map"] == [["Q1", True], ["Q2", False]]


def test_unreadable_csv_leaves_no_orphan_job(client, user_factory, login, app_module_fixture):
    # the job document was inserted before the files were read, so a failed
    # upload left a SPLIT job with no files in the history forever
    user_factory("alice")
    token = login("alice")
    data = {
        "user_id": "alice",
        "token": token,
        "front_template_id": "front",
        "regular_template_id": "regular",
        "front_template_name": "front",
        "regular_template_name": "regular",
        "job_name": "exam",
        "statistics_for_students": "true",
        "n_pages_per_question": json.dumps([["Q1", 1]]),
        "n_max_points_per_question": json.dumps([["Q1", 5]]),
        "bonus_enabled_map": json.dumps([["Q1", False]]),
        "notes_csv_file": (io.BytesIO(b""), "notes.csv"),  # empty: pandas raises
        "zip_file": (io.BytesIO(b"PK\x05\x06" + b"\x00" * 18), "copies.zip"),
    }
    resp = client.post("/jobs/evaluate", data=data, content_type="multipart/form-data")
    assert resp.status_code == 500
    assert app_module_fixture.mongo["RMN"]["eval_jobs"].count_documents({}) == 0


# --------------------------------------------------- a task from another one --
def _source_task(app_module_fixture, storage_root, user="alice", job_id="source"):
    """A task of ``user`` with its notes and two zips on the share."""
    app_module_fixture.mongo["RMN"]["eval_jobs"].insert_one(
        {
            "job_id": job_id,
            "user_id": user,
            "job_name": "Intra",
            "notes_file_id": os.path.join("csv", f"{job_id}.csv"),
        }
    )
    csv = storage_root / "csv" / f"{job_id}.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    csv.write_bytes(b"Matricule,Nom complet\n1234567,Alice\n")
    zips = storage_root / "zips" / job_id
    zips.mkdir(parents=True, exist_ok=True)
    (zips / "a.zip").write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    (zips / "b.zip").write_bytes(b"PK\x05\x06" + b"\x01" * 18)
    return job_id


def _from_source(client, user, token, source_job_id, files=None, name="Intra bis"):
    data = {
        "user_id": user,
        "token": token,
        "front_template_id": "front",
        "regular_template_id": "regular",
        "front_template_name": "front",
        "regular_template_name": "regular",
        "job_name": name,
        "statistics_for_students": "true",
        "n_pages_per_question": json.dumps([["Q1", 2]]),
        "n_max_points_per_question": json.dumps([["Q1", 10]]),
        "bonus_enabled_map": json.dumps([["Q1", False]]),
        "source_job_id": source_job_id,
        **(files or {}),
    }
    return client.post("/jobs/evaluate", data=data, content_type="multipart/form-data")


def test_a_task_created_from_another_one_reuses_its_copies_and_notes(
    client, user_factory, login, app_module_fixture, storage_root
):
    user_factory("alice")
    token = login("alice")
    source = _source_task(app_module_fixture, storage_root)

    resp = _from_source(client, "alice", token, source)

    assert resp.status_code == 200, resp.data
    new = app_module_fixture.mongo["RMN"]["eval_jobs"].find_one({"job_name": "Intra bis"})
    job_id = new["job_id"]
    assert job_id != source
    # the files are copied, never shared: deleting either task takes its own
    copied = sorted(p.name for p in (storage_root / "zips" / job_id).iterdir())
    assert len(copied) == 2
    assert {(storage_root / "zips" / job_id / n).read_bytes()
            for n in copied} == {b"PK\x05\x06" + b"\x00" * 18, b"PK\x05\x06" + b"\x01" * 18}
    assert (storage_root / "csv" / f"{job_id}.csv").read_bytes().startswith(b"Matricule")
    # and the source keeps everything it had
    assert len(list((storage_root / "zips" / source).iterdir())) == 2


def test_a_file_that_is_uploaded_replaces_the_one_of_the_source(
    client, user_factory, login, app_module_fixture, storage_root
):
    """The point of the switch in the wizard: keep the copies, change the notes."""
    user_factory("alice")
    token = login("alice")
    source = _source_task(app_module_fixture, storage_root)

    resp = _from_source(
        client, "alice", token, source,
        files={"notes_csv_file": (io.BytesIO(b"Matricule,Nom complet\n7654321,Bob\n"), "new.csv")},
    )

    assert resp.status_code == 200, resp.data
    job_id = app_module_fixture.mongo["RMN"]["eval_jobs"].find_one(
        {"job_name": "Intra bis"})["job_id"]
    assert b"7654321" in (storage_root / "csv" / f"{job_id}.csv").read_bytes()
    assert len(list((storage_root / "zips" / job_id).iterdir())) == 2  # copies kept


def test_a_task_of_another_user_cannot_be_the_source(
    client, user_factory, login, app_module_fixture, storage_root
):
    user_factory("alice")
    user_factory("bob")
    token = login("bob")
    source = _source_task(app_module_fixture, storage_root)  # alice's

    resp = _from_source(client, "bob", token, source)

    assert resp.status_code == 404
    assert app_module_fixture.mongo["RMN"]["eval_jobs"].find_one({"job_name": "Intra bis"}) is None


def test_a_source_whose_files_are_gone_is_refused_before_anything_is_created(
    client, user_factory, login, app_module_fixture, storage_root
):
    """The copies of an old task are swept once it is archived; say so, and do
    not leave a task behind that could never be split."""
    user_factory("alice")
    token = login("alice")
    source = _source_task(app_module_fixture, storage_root)
    shutil.rmtree(storage_root / "zips" / source)

    resp = _from_source(client, "alice", token, source)

    assert resp.status_code == 400
    assert "copies" in resp.get_json(force=True)["response"]
    assert app_module_fixture.mongo["RMN"]["eval_jobs"].find_one({"job_name": "Intra bis"}) is None


def test_the_legacy_single_zip_of_an_old_task_is_reused_too(
    client, user_factory, login, app_module_fixture, storage_root
):
    user_factory("alice")
    token = login("alice")
    source = _source_task(app_module_fixture, storage_root)
    shutil.rmtree(storage_root / "zips" / source)
    (storage_root / "zips" / f"{source}.zip").write_bytes(b"PK\x05\x06" + b"\x02" * 18)

    resp = _from_source(client, "alice", token, source)

    assert resp.status_code == 200, resp.data
    job_id = app_module_fixture.mongo["RMN"]["eval_jobs"].find_one(
        {"job_name": "Intra bis"})["job_id"]
    assert len(list((storage_root / "zips" / job_id).iterdir())) == 1


def test_without_a_source_both_files_are_still_required(client, user_factory, login):
    user_factory("alice")
    token = login("alice")
    data = {
        "user_id": "alice", "token": token,
        "front_template_id": "f", "regular_template_id": "r",
        "front_template_name": "f", "regular_template_name": "r",
        "job_name": "exam", "statistics_for_students": "true",
        "n_pages_per_question": json.dumps([["Q1", 2]]),
        "n_max_points_per_question": json.dumps([["Q1", 10]]),
        "bonus_enabled_map": json.dumps([["Q1", False]]),
        "zip_file": (io.BytesIO(b"PK\x05\x06" + b"\x00" * 18), "copies.zip"),
    }
    resp = client.post("/jobs/evaluate", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "notes_csv_file" in resp.get_json(force=True)["response"]
