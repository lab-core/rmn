"""Listing, fetching, versioning and saving the copies of a job.

A job-wide or matricule link sees the whole copies, a question link only the
pages of its question; the owner sees everything. Every saved copy becomes a
new version whose base pdf and annotation layers can be fetched back.
"""

import io
import json
import os
import uuid

import pytest

TOKENS = {"mat": "tok-mat", "1": "tok-q1", "questions": "tok-q", "all": "tok-all"}


def _put(storage, rel, content):
    path = storage.abs_path(rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


@pytest.fixture
def job(user_factory, job_factory, app_module_fixture):
    """alice's job: one copy, cut into Q1 (document 0) and Q2 (document 1).

    Each question pdf is on disk with its initial version (version 0), as the
    executor leaves them after the split.
    """
    user_factory("alice")
    # a fresh id per test: the storage root outlives a test
    job_id = f"docs-{uuid.uuid4().hex[:8]}"
    job_factory(job_id, "alice", share_token=dict(TOKENS))
    db = app_module_fixture.mongo["RMN"]
    storage = app_module_fixture.storage
    _put(storage, f"cover_pages/{job_id}/copy1_cover.pdf", b"%PDF cover")
    db["job_documents"].insert_one(
        {
            "job_id": job_id,
            "document_index": 0,
            "filename": "copy1",
            "matricule": "1234567",
            "grades": [None, None],
            "status": "TO VALIDATE",
            "execution_time": 1.5,
            "rel_filepath": f"cover_pages/{job_id}/copy1_cover.pdf",
        }
    )
    for index, question in ((0, "Q1"), (1, "Q2")):
        rel = f"documents/{job_id}/{question}/copy1_{question}.pdf"
        version = f"documents/{job_id}/{question}/versions/copy1_{question}-0.pdf"
        _put(storage, rel, f"%PDF current {question}".encode())
        _put(storage, version, f"%PDF initial {question}".encode())
        db["job_questions"].insert_one(
            {
                "job_id": job_id,
                "document_index": index,
                "question_index": index + 1,
                "question": question,
                "basename": "copy1",
                "filename": f"copy1_{question}",
                "rel_filepath": rel,
                "status": "TO VALIDATE",
                "grade": None,
            }
        )
        db["versions"].insert_one(
            {
                "job_id": job_id,
                "rel_filepath": rel,
                "version": 0,
                "version_filepath": version,
                "annotations": [],
            }
        )
    return job_id


@pytest.fixture
def db(app_module_fixture):
    return app_module_fixture.mongo["RMN"]


@pytest.fixture
def redis_queue(app_module_fixture):
    return lambda: app_module_fixture.redis.lrange("job_queue", 0, -1)


@pytest.fixture
def owner(login):
    """The owner's form fields (the job id is added per request)."""
    return {"token": login("alice")}


def _q1(**extra):
    return {"share_token": "tok-q1", "question_index": "1", **extra}


# -------------------------------------------------------------- /documents ---
def _list(client, job_id, auth, **extra):
    resp = client.post("/documents", data={"job_id": job_id, **auth, **extra})
    return resp.status_code, resp.get_json(force=True)


def test_owner_lists_the_copies(client, job, owner):
    status, body = _list(client, job, owner)
    assert status == 200
    [doc] = body["response"]
    assert doc["matricule"] == "1234567" and doc["exec_time"] == 1.5
    assert doc["n_total_doc"] == 1 and doc["group"] == ""


def test_owner_lists_the_questions_filtered_by_index(client, job, owner):
    status, body = _list(
        client, job, owner, questions="true", documents_indices=json.dumps([1])
    )
    assert status == 200
    assert [d["question"] for d in body["response"]] == ["Q2"]
    assert body["response"][0]["n_total_doc"] == 1


def test_a_question_link_lists_only_its_own_question(client, job):
    status, body = _list(client, job, _q1(), questions="true")
    assert status == 200
    assert [d["question"] for d in body["response"]] == ["Q1"]


@pytest.mark.parametrize("share_token", ["tok-q", "tok-all"])
def test_a_job_wide_question_link_lists_every_question(client, job, share_token):
    status, body = _list(client, job, {"share_token": share_token}, questions="true")
    assert status == 200
    assert [d["question"] for d in body["response"]] == ["Q1", "Q2"]


def test_a_matricule_link_sees_the_copies_but_not_the_questions(client, job):
    assert _list(client, job, {"share_token": "tok-mat"})[0] == 200
    assert _list(client, job, {"share_token": "tok-mat"}, questions="true")[0] == 401


def test_a_question_link_cannot_list_the_whole_copies(client, job):
    status, body = _list(client, job, _q1())
    assert status == 401
    assert "response" not in body


def test_non_consecutive_question_documents_are_refused(client, job, owner, db):
    db["job_questions"].update_one(
        {"job_id": job, "document_index": 1}, {"$set": {"document_index": 3}}
    )
    status, body = _list(client, job, owner, questions="true")
    assert status == 400
    assert "consecutive" in body["Error"]


# ------------------------------------------------------- /document/download ---
def _download(client, job_id, auth, **extra):
    return client.post("/documents/download", data={"job_id": job_id, **auth, **extra})


def test_owner_downloads_the_cover_page_of_a_copy(client, job, owner):
    resp = _download(client, job, owner, document_index="0")
    assert resp.status_code == 200
    assert resp.data == b"%PDF cover"


def test_a_question_download_serves_the_base_of_the_last_version(client, job, owner):
    resp = _download(client, job, owner, document_index="0", questions="true")
    assert resp.status_code == 200
    # the pdf of the version, without the annotations drawn on the current one
    assert resp.data == b"%PDF initial Q1"


def test_with_annotations_serves_the_current_pdf(client, job, owner):
    resp = _download(
        client, job, owner, document_index="1", questions="true", with_annotations="1"
    )
    assert resp.status_code == 200
    assert resp.data == b"%PDF current Q2"


def test_with_annotations_and_a_version_is_refused(client, job, owner):
    resp = _download(
        client,
        job,
        owner,
        document_index="1",
        questions="true",
        with_annotations="1",
        version="0",
    )
    assert resp.status_code == 400


def test_an_unknown_version_is_refused(client, job, owner):
    resp = _download(
        client, job, owner, document_index="0", questions="true", version="7"
    )
    assert resp.status_code == 400


def test_a_question_link_downloads_only_its_own_question(client, job):
    assert _download(client, job, _q1(), document_index="0", questions="true").data == (
        b"%PDF initial Q1"
    )
    resp = _download(client, job, _q1(), document_index="1", questions="true")
    assert resp.status_code == 401
    assert b"%PDF" not in resp.data
    # nor the whole copy
    assert _download(client, job, _q1(), document_index="0").status_code == 401


def test_a_matricule_link_downloads_the_copy_but_not_a_question(client, job):
    mat = {"share_token": "tok-mat"}
    assert _download(client, job, mat, document_index="0").data == b"%PDF cover"
    resp = _download(client, job, mat, document_index="0", questions="true")
    assert resp.status_code == 401


def test_download_of_an_unknown_document_is_404(client, job, owner):
    assert _download(client, job, owner, document_index="9").status_code == 404
    resp = _download(client, job, owner, document_index="9", questions="true")
    assert resp.status_code == 404
    assert _download(client, job, owner).status_code == 400


def test_another_user_cannot_download_a_copy(client, job, user_factory, login):
    user_factory("bob")
    resp = _download(client, job, {"token": login("bob")}, document_index="0")
    assert resp.status_code == 401
    assert b"%PDF" not in resp.data


# ------------------------------------------------- versions and annotations ---
def test_last_version_counts_the_stored_versions(client, job, owner):
    resp = client.post(
        "/documents/last_version", data={"job_id": job, **owner, "document_index": "0"}
    )
    assert resp.status_code == 200
    assert resp.get_json(force=True) == {"last_version": 0}
    missing = {"job_id": job, **owner}
    assert client.post("/documents/last_version", data=missing).status_code == 400
    unknown = {**missing, "document_index": "9"}
    assert client.post("/documents/last_version", data=unknown).status_code == 404


def _annotations(client, job_id, auth, **extra):
    return client.post(
        "/documents/annotations",
        data={"job_id": job_id, "questions": "true", **auth, **extra},
    )


def test_annotations_of_the_last_version(client, job, owner, db):
    db["versions"].update_one(
        {"job_id": job, "version": 0, "rel_filepath": {"$regex": "Q1"}},
        {"$set": {"annotations": [{"layer": 1}]}},
    )
    resp = _annotations(client, job, owner, document_index="0")
    assert resp.status_code == 200
    assert resp.get_json(force=True) == {
        "annotations": [{"layer": 1}],
        "last_version": 0,
    }


def test_annotations_of_a_version_that_does_not_exist(client, job, owner):
    resp = _annotations(client, job, owner, document_index="0", version="4")
    assert resp.status_code == 200
    assert "annotations" not in resp.get_json(force=True)


def test_a_question_link_reads_only_its_own_annotations(client, job):
    assert _annotations(client, job, _q1(), document_index="0").status_code == 200
    assert _annotations(client, job, _q1(), document_index="1").status_code == 404


def test_annotations_need_a_known_document(client, job, owner):
    assert _annotations(client, job, owner, document_index="9").status_code == 404
    assert _annotations(client, job, owner).status_code == 400


# --------------------------------------------------------- /document/update ---
def _save(client, job_id, auth, pdf=None, name=None, **extra):
    data = {"job_id": job_id, "status": "TO VALIDATE", **auth, **extra}
    if pdf is not None:
        data["file"] = (io.BytesIO(pdf), name)
    return client.post(
        "/documents/update", data=data, content_type="multipart/form-data"
    )


def test_saving_annotations_stores_a_version_on_the_requested_base(
    client, job, owner, db, app_module_fixture
):
    resp = _save(
        client,
        job,
        owner,
        b"%PDF annotated",
        "copy1_Q1.pdf",
        document_index="0",
        version="0",
        annotations=json.dumps([{"ink": 1}]),
    )

    assert resp.status_code == 200, resp.data
    storage = app_module_fixture.storage
    with open(storage.abs_path(f"documents/{job}/Q1/copy1_Q1.pdf"), "rb") as f:
        assert f.read() == b"%PDF annotated"
    new = db["versions"].find_one({"job_id": job, "version": 1})
    assert new["rel_filepath"] == f"documents/{job}/Q1/copy1_Q1.pdf"
    assert new["version_filepath"] == f"documents/{job}/Q1/versions/copy1_Q1-0.pdf"
    assert new["annotations"] == [{"ink": 1}]
    # and it is what is served back
    resp = _annotations(client, job, owner, document_index="0")
    assert resp.get_json(force=True) == {"annotations": [{"ink": 1}], "last_version": 1}
    resp = _download(
        client, job, owner, document_index="0", questions="true", version="1"
    )
    assert resp.data == b"%PDF initial Q1"


def test_a_restored_copy_is_saved_on_a_backup_of_the_current_pdf(
    client, job, owner, db, app_module_fixture
):
    # version -1: the teacher restored the copy, so the current pdf (with its
    # flattened annotations) becomes the base of the new version
    resp = _save(
        client,
        job,
        owner,
        b"%PDF new",
        "copy1_Q2.pdf",
        document_index="1",
        version="-1",
        annotations="[]",
    )

    assert resp.status_code == 200, resp.data
    new = db["versions"].find_one({"job_id": job, "version": 1})
    with open(new["version_filepath"], "rb") as f:
        assert f.read() == b"%PDF current Q2"
    storage = app_module_fixture.storage
    assert new["version_filepath"] != storage.abs_path(
        f"documents/{job}/Q2/versions/copy1_Q2-0.pdf"
    )
    with open(storage.abs_path(f"documents/{job}/Q2/copy1_Q2.pdf"), "rb") as f:
        assert f.read() == b"%PDF new"


def test_a_question_link_cannot_save_a_file_named_after_another_question(
    client, job, db, app_module_fixture
):
    # the document is its own (Q1); only the file name points at Q2
    resp = _save(client, job, _q1(), b"%PDF evil", "copy1_Q2.pdf", document_index="0")
    assert resp.status_code == 401
    with open(
        app_module_fixture.storage.abs_path(f"documents/{job}/Q2/copy1_Q2.pdf"), "rb"
    ) as f:
        assert f.read() == b"%PDF current Q2"
    assert db["versions"].count_documents({"job_id": job}) == 2


def test_a_question_link_cannot_save_the_whole_copy(client, job, app_module_fixture):
    resp = _save(client, job, _q1(), b"%PDF evil", "copy1_all.pdf", document_index="0")
    assert resp.status_code == 401
    assert not os.path.exists(
        app_module_fixture.storage.abs_path(f"documents/{job}/all/copy1_all.pdf")
    )


def test_a_question_link_grades_its_question_and_the_copy(client, job, db):
    resp = _save(
        client, job, _q1(), document_index="0", status="validated", grades="4.5"
    )
    assert resp.status_code == 200, resp.data
    q1 = db["job_questions"].find_one({"job_id": job, "document_index": 0})
    assert (q1["status"], q1["grade"]) == ("VALIDATED", 4.5)
    assert db["job_documents"].find_one({"job_id": job})["grades"] == [4.5, None]


def test_a_tag_alone_updates_the_question(client, job, owner, db):
    resp = _save(
        client, job, owner, document_index="1", question_index="2", tag="doubt"
    )
    assert resp.status_code == 200
    q2 = db["job_questions"].find_one({"job_id": job, "document_index": 1})
    assert (q2["tag"], q2["grade"], q2["status"]) == ("doubt", None, "TO VALIDATE")


def test_update_of_an_unknown_question_is_404(client, job, owner):
    resp = _save(client, job, owner, document_index="9", question_index="1", grades="1")
    assert resp.status_code == 404


def test_grading_a_question_of_a_missing_copy_is_404(client, job, owner, db):
    # the question is there, the job_documents row of its copy is not
    db["job_documents"].delete_many({"job_id": job})
    resp = _save(
        client, job, owner, document_index="0", question_index="1", grades="2"
    )
    assert resp.status_code == 404, resp.data
    assert resp.get_json(force=True) == {"response": "Error: document copy1 not found."}


@pytest.mark.parametrize(
    "extra",
    [
        {"status": "PERFECT"},
        # annotations without the version they were drawn on
        {"status": "TO VALIDATE", "annotations": "[]"},
        {},
    ],
    ids=["unknown-status", "annotations-without-version", "no-status"],
)
def test_update_refuses_a_malformed_request(client, job, owner, db, extra):
    form = {"job_id": job, **owner, "document_index": "0", "grades": "3", **extra}
    resp = client.post("/documents/update", data={**form, "question_index": "1"})
    assert resp.status_code == 400
    q1 = db["job_questions"].find_one({"job_id": job, "document_index": 0})
    assert (q1["status"], q1["grade"]) == ("TO VALIDATE", None)


# ------------------------------------------------ /documents/replace, tags ---
def test_replace_needs_a_file(client, job, owner):
    resp = client.post("/documents/replace", data={"job_id": job, **owner})
    assert resp.status_code == 400


def test_tag_needs_every_field(client, job, owner):
    resp = client.post("/documents/tag", data={"job_id": job, **owner, "tag": "x"})
    assert resp.status_code == 400


def test_read_grades_of_a_job_without_questions_is_refused(
    client, job, job_factory, owner, redis_queue
):
    job_factory("no-questions", "alice")
    before = redis_queue()
    resp = client.post("/documents/read_grades", data={"job_id": "no-questions", **owner})
    assert resp.status_code == 401
    assert redis_queue() == before


# ------------------------------------------------------- malformed numbers ---
@pytest.mark.parametrize(
    "route,field,extra",
    [
        ("/documents/tag", "document_index", {"tag": "t"}),
        ("/documents/update", "document_index", {"status": "TO VALIDATE"}),
        (
            "/documents/update",
            "version",
            {"status": "TO VALIDATE", "annotations": "[]"},
        ),
        (
            "/documents/update",
            "question_index",
            {"status": "VALIDATED", "grades": "3"},
        ),
        ("/documents/download", "document_index", {}),
        ("/documents/download", "version", {"questions": "true"}),
        ("/documents/last_version", "document_index", {}),
        ("/documents/annotations", "document_index", {"questions": "true"}),
        ("/documents/annotations", "version", {"questions": "true"}),
    ],
    ids=[
        "tag",
        "update",
        "update-version",
        "update-question",
        "download",
        "download-version",
        "last-version",
        "annotations",
        "annotations-version",
    ],
)
def test_a_malformed_number_is_400(client, job, owner, db, route, field, extra):
    form = {"job_id": job, **owner, "document_index": "0", **extra, field: "x"}
    resp = client.post(route, data=form)
    # a bare int() made it a 500
    assert resp.status_code == 400, resp.data
    assert resp.get_json(force=True) == {"response": f"Error: {field} is not a number."}
    # refused before any write: a bad question_index used to fail after the
    # question had been graded
    q1 = db["job_questions"].find_one({"job_id": job, "document_index": 0})
    assert (q1["status"], q1["grade"], q1.get("tag")) == ("TO VALIDATE", None, None)
