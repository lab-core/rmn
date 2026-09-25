"""Validation of the per-question lists sent to ``/evaluate``.

A question with 0 page and 0 point is *ignored*: the template has a box for it
but the exam does not use it. Any other 0 or negative value is refused.
"""

import io
import json
import os
import shutil
import zipfile

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
    shutil.rmtree(storage_root / "zips" / source)  # nothing left to zip up either

    resp = _from_source(client, "alice", token, source)

    assert resp.status_code == 400
    assert "copies" in resp.get_json(force=True)["response"]
    assert app_module_fixture.mongo["RMN"]["eval_jobs"].find_one({"job_name": "Intra bis"}) is None


def test_the_copies_of_a_task_already_split_are_zipped_up_again(
    client, user_factory, login, app_module_fixture, storage_root
):
    """The usual case: the executor deletes a zip as soon as it has split it,
    so a task worth duplicating keeps its copies in documents/<job>/all."""
    user_factory("alice")
    token = login("alice")
    source = _source_task(app_module_fixture, storage_root)
    shutil.rmtree(storage_root / "zips" / source)
    copies = storage_root / "documents" / source / "all"
    copies.mkdir(parents=True)
    (copies / "Alice_Tremblay_1234567.pdf").write_bytes(b"%PDF-1.4 alice")
    (copies / "Bob_Gagnon_7654321.pdf").write_bytes(b"%PDF-1.4 bob")

    resp = _from_source(client, "alice", token, source)

    assert resp.status_code == 200, resp.data
    job_id = app_module_fixture.mongo["RMN"]["eval_jobs"].find_one(
        {"job_name": "Intra bis"})["job_id"]
    written = list((storage_root / "zips" / job_id).iterdir())
    assert len(written) == 1
    with zipfile.ZipFile(written[0]) as archive:
        # the copies keep the names they had in the zip they arrived in
        assert sorted(archive.namelist()) == [
            "Alice_Tremblay_1234567.pdf", "Bob_Gagnon_7654321.pdf"]
        assert archive.read("Bob_Gagnon_7654321.pdf") == b"%PDF-1.4 bob"
    # and the source keeps its own
    assert len(list(copies.iterdir())) == 2


def test_a_source_with_neither_a_zip_nor_a_copy_is_refused(
    client, user_factory, login, app_module_fixture, storage_root
):
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


# ------------------------------------------- a task shared by someone else --
def _shared_source(app_module_fixture, storage_root, share_token=None, rendered=True):
    """alice's task, with her two templates on the share, shared as given."""
    db = app_module_fixture.mongo["RMN"]
    source = _source_task(app_module_fixture, storage_root)
    db["eval_jobs"].update_one(
        {"job_id": source},
        {"$set": {"front_template_id": "front", "regular_template_id": "regular",
                  "share_token": share_token or {"all": "dash-token"}}},
    )
    for template_id, name in (("front", "Front"), ("regular", "Regular")):
        template = {
            "template_id": template_id,
            "user_id": "alice",
            "template_name": name,
            "template_file_id": f"template/{template_id}.png",
            "grade_box": [0.1, 0.2, 0.3, 0.4],
            "n_questions": 1,
            "locked": False,
        }
        (storage_root / "template").mkdir(parents=True, exist_ok=True)
        (storage_root / "template" / f"{template_id}.png").write_bytes(name.encode())
        if rendered:
            rendered_id = f"template/{template_id}-rendered.png"
            template["template_rendered_file_id"] = rendered_id
            (storage_root / rendered_id).write_bytes(b"r")
        db["template"].insert_one(template)
    return source


def _from_shared(client, token, source, share_token="dash-token", **fields):
    data = {
        "user_id": "bob",
        "token": token,
        "front_template_id": "front",
        "regular_template_id": "regular",
        "front_template_name": "Front",
        "regular_template_name": "Regular",
        "job_name": "Intra bob",
        "statistics_for_students": "true",
        "n_pages_per_question": json.dumps([["Q1", 2]]),
        "n_max_points_per_question": json.dumps([["Q1", 10]]),
        "bonus_enabled_map": json.dumps([["Q1", False]]),
        "source_job_id": source,
        "source_share_token": share_token,
        **fields,
    }
    return client.post("/jobs/evaluate", data=data, content_type="multipart/form-data")


def test_a_task_shared_by_its_dashboard_link_can_be_duplicated(
    client, user_factory, login, app_module_fixture, storage_root
):
    db = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    user_factory("bob")
    source = _shared_source(app_module_fixture, storage_root)

    resp = _from_shared(client, login("bob"), source)

    assert resp.status_code == 200, resp.data
    new = db["eval_jobs"].find_one({"job_name": "Intra bob"})
    assert new["user_id"] == "bob"
    assert len(list((storage_root / "zips" / new["job_id"]).iterdir())) == 2
    csv = storage_root / "csv" / f"{new['job_id']}.csv"
    assert csv.read_bytes().startswith(b"Matricule")
    # the task points at bob's own copies of alice's templates
    front = db["template"].find_one({"template_id": new["front_template_id"]})
    regular = db["template"].find_one({"template_id": new["regular_template_id"]})
    assert front["user_id"] == regular["user_id"] == "bob"
    assert (front["copied_from"], regular["copied_from"]) == ("front", "regular")
    names = (new["front_template_name"], new["regular_template_name"])
    assert names == ("Front", "Regular")
    assert front["grade_box"] == [0.1, 0.2, 0.3, 0.4] and front["n_questions"] == 1
    assert (storage_root / front["template_file_id"]).read_bytes() == b"Front"
    assert (storage_root / front["template_rendered_file_id"]).read_bytes() == b"r"
    # alice keeps hers untouched
    assert db["template"].count_documents({"user_id": "alice"}) == 2


@pytest.mark.parametrize(
    "share_token,sent",
    [
        ({"all": "dash-token"}, "wrong"),  # not the link's token
        ({"all": "dash-token"}, ""),  # no token at all
        ({"questions": "q-token"}, "q-token"),  # correction link: not the task
        ({"2": "q2-token"}, "q2-token"),  # one question only
    ],
)
def test_only_the_dashboard_link_lets_another_user_duplicate(
    client, user_factory, login, app_module_fixture, storage_root, share_token, sent
):
    db = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    user_factory("bob")
    source = _shared_source(app_module_fixture, storage_root, share_token=share_token)

    resp = _from_shared(client, login("bob"), source, share_token=sent)

    assert resp.status_code == 404
    assert db["eval_jobs"].find_one({"job_name": "Intra bob"}) is None
    assert db["template"].count_documents({"user_id": "bob"}) == 0


def test_a_second_duplicate_reuses_the_template_copies(
    client, user_factory, login, app_module_fixture, storage_root
):
    db = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    user_factory("bob")
    source = _shared_source(app_module_fixture, storage_root)
    token = login("bob")

    first = _from_shared(client, token, source, job_name="first")
    second = _from_shared(client, token, source, job_name="second")

    assert first.status_code == second.status_code == 200
    jobs = {j["job_name"]: j for j in db["eval_jobs"].find({"user_id": "bob"})}
    assert jobs["first"]["front_template_id"] == jobs["second"]["front_template_id"]
    assert db["template"].count_documents({"user_id": "bob"}) == 2


def test_a_template_copy_does_not_hide_one_of_the_same_name(
    client, user_factory, login, app_module_fixture, storage_root
):
    db = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    user_factory("bob")
    source = _shared_source(app_module_fixture, storage_root)
    db["template"].insert_one(
        {"template_id": "bobs", "user_id": "bob", "template_name": "Front",
         "template_file_id": "template/bobs.png"}
    )

    resp = _from_shared(client, login("bob"), source)

    assert resp.status_code == 200, resp.data
    new = db["eval_jobs"].find_one({"job_name": "Intra bob"})
    assert new["front_template_name"] == "Front (alice)"
    assert new["regular_template_name"] == "Regular"


def test_a_template_of_their_own_picked_in_the_wizard_is_not_copied(
    client, user_factory, login, app_module_fixture, storage_root
):
    db = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    user_factory("bob")
    source = _shared_source(app_module_fixture, storage_root)
    db["template"].insert_one(
        {"template_id": "bobs", "user_id": "bob", "template_name": "Mine",
         "template_file_id": "template/bobs.png"}
    )

    resp = _from_shared(client, login("bob"), source,
                        front_template_id="bobs", front_template_name="Mine")

    assert resp.status_code == 200, resp.data
    new = db["eval_jobs"].find_one({"job_name": "Intra bob"})
    assert (new["front_template_id"], new["front_template_name"]) == ("bobs", "Mine")
    assert db["template"].find_one({"user_id": "bob", "copied_from": "front"}) is None
    assert db["template"].find_one({"user_id": "bob", "copied_from": "regular"})


def test_only_the_templates_of_the_source_are_copied(
    client, user_factory, login, app_module_fixture, storage_root
):
    """A shared source must not be a way to copy any template whose id is known."""
    db = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    user_factory("bob")
    source = _shared_source(app_module_fixture, storage_root)
    db["template"].insert_one(
        {"template_id": "other", "user_id": "carol", "template_name": "Carol's",
         "template_file_id": "template/other.png"}
    )
    (storage_root / "template" / "other.png").write_bytes(b"carol")

    resp = _from_shared(client, login("bob"), source, front_template_id="other")

    assert resp.status_code == 200, resp.data
    assert db["template"].find_one({"user_id": "bob", "copied_from": "other"}) is None


def test_a_deleted_template_of_the_source_is_refused_before_anything_is_created(
    client, user_factory, login, app_module_fixture, storage_root
):
    db = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    user_factory("bob")
    source = _shared_source(app_module_fixture, storage_root)
    db["template"].delete_one({"template_id": "regular"})

    resp = _from_shared(client, login("bob"), source)

    assert resp.status_code == 400
    assert "template" in resp.get_json(force=True)["response"]
    assert db["eval_jobs"].find_one({"job_name": "Intra bob"}) is None


def test_a_locked_default_template_is_used_as_it_is(
    client, user_factory, login, app_module_fixture, storage_root
):
    db = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    user_factory("bob")
    source = _shared_source(app_module_fixture, storage_root)
    db["template"].update_one({"template_id": "regular"}, {"$set": {"locked": True}})

    resp = _from_shared(client, login("bob"), source)

    assert resp.status_code == 200, resp.data
    new = db["eval_jobs"].find_one({"job_name": "Intra bob"})
    assert new["regular_template_id"] == "regular"
    assert db["template"].find_one({"user_id": "bob", "copied_from": "regular"}) is None


def test_a_template_never_rendered_is_queued_for_rendering(
    client, user_factory, login, app_module_fixture, storage_root
):
    from service import template_service

    user_factory("alice")
    user_factory("bob")
    source = _shared_source(app_module_fixture, storage_root, rendered=False)
    # a queue of its own, separate from the app's, which _isolate_state does
    # not wipe: leave it empty for the template tests that read it after
    template_service.redis.delete("job_queue")
    try:
        resp = _from_shared(client, login("bob"), source)
        queued = template_service.redis.lrange("job_queue", 0, -1)
    finally:
        template_service.redis.delete("job_queue")

    assert resp.status_code == 200, resp.data
    db = app_module_fixture.mongo["RMN"]
    new = db["eval_jobs"].find_one({"job_name": "Intra bob"})
    assert {"template_id": new["front_template_id"]} in [json.loads(m) for m in queued]


def test_the_wizard_reads_a_shared_task_with_the_session_and_the_link(
    client, user_factory, login, job_factory
):
    """How the wizard prefills a colleague's task: bob's session in the
    Authorization header, the dashboard link's token in the form."""
    user_factory("alice")
    user_factory("bob")
    job_factory("shared", "alice", queued_time="2026-09-25", job_name="Intra",
                statistics_for_students=False, share_token={"all": "dash-token"})
    headers = {"Authorization": f"Bearer {login('bob')}"}

    resp = client.post("/jobs/info", headers=headers,
                       data={"job_id": "shared", "user_id": "bob",
                             "share_token": "dash-token"})
    assert resp.status_code == 200, resp.data
    assert resp.get_json(force=True)["response"]["job_name"] == "Intra"

    resp = client.post("/jobs/info", headers=headers,
                       data={"job_id": "shared", "user_id": "bob"})
    assert resp.status_code == 401  # not without the link
