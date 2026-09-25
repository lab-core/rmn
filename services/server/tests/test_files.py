"""Downloading the output files of a finished task, and the link that shares them.

The owner, the archive link (``jobs_output.share_token``) and the job-wide
link (``share_token.all``) may download; a question or matricule link, another
user or another job's link may not. The stored file ids come from the
database, never from the request, so the only client input that reaches the
storage is an index into ``zip_id_list``.
"""

import os
import uuid

import pytest
from context import TEMP_FOLDER


def _put(storage, rel, content):
    path = storage.abs_path(rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


@pytest.fixture
def finished(user_factory, job_factory, app_module_fixture):
    """A finished job of alice's with its csv, stats and two zips on disk."""
    user_factory("alice")
    # a fresh id per test: the storage root outlives a test
    job_id = f"files-{uuid.uuid4().hex[:8]}"
    job_factory(
        job_id,
        "alice",
        status="ARCHIVED",
        share_token={"all": "tok-all", "questions": "tok-q", "mat": "tok-mat"},
    )
    storage = app_module_fixture.storage
    _put(storage, f"output_csv/{job_id}.csv", b"Matricule,Note\n1,10\n")
    _put(storage, f"output_stats/{job_id}.pdf", b"%PDF-1.4 stats")
    _put(storage, f"output_zip/{job_id}_0.zip", b"ZIP0")
    _put(storage, f"output_zip/{job_id}_1.zip", b"ZIP1")
    app_module_fixture.mongo["RMN"]["jobs_output"].insert_one(
        {
            "job_id": job_id,
            "user_id": "alice",
            "notes_csv_file_id": f"output_csv/{job_id}.csv",
            "stats_file_id": f"output_stats/{job_id}.pdf",
            "preview_file_id": "None",
            "zip_id_list": [f"output_zip/{job_id}_0.zip", f"output_zip/{job_id}_1.zip"],
            "share_token": "tok-file",
        }
    )
    return job_id


def _download(client, job_id, **params):
    return client.get("/files/download", query_string={"job_id": job_id, **params})


def _temp_files():
    return set(os.listdir(TEMP_FOLDER)) if os.path.isdir(TEMP_FOLDER) else set()


def test_owner_downloads_the_notes_csv_as_an_attachment(client, finished, login):
    before = _temp_files()
    resp = _download(
        client, finished, token=login(), file="notes_csv_file", filename="notes.csv"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data == b"Matricule,Note\n1,10\n"
    assert "attachment" in resp.headers["Content-Disposition"]
    assert "notes.csv" in resp.headers["Content-Disposition"]
    resp.close()
    # the local copy made for send_file does not pile up in the temp folder
    assert _temp_files() == before


def test_owner_downloads_the_stats_by_post(client, finished, login):
    resp = client.post(
        "/files/download",
        data={"job_id": finished, "token": login(), "file": "stats_pdf_file"},
    )
    assert resp.status_code == 200
    assert resp.data == b"%PDF-1.4 stats"


@pytest.mark.parametrize("index,content", [("0", b"ZIP0"), ("1", b"ZIP1")])
def test_a_zip_is_picked_by_its_index(client, finished, login, index, content):
    resp = _download(client, finished, token=login(), file="zip_file", zip_index=index)
    assert resp.status_code == 200
    assert resp.data == content


def test_a_zip_download_needs_its_index(client, finished, login):
    assert (
        _download(client, finished, token=login(), file="zip_file").status_code == 400
    )


@pytest.mark.parametrize("file", ["../../etc/passwd", "notes_csv_file_id", ""])
def test_only_the_known_output_files_can_be_asked_for(client, finished, login, file):
    resp = _download(client, finished, token=login(), file=file)
    assert resp.status_code == 404
    assert b"root:" not in resp.data


def test_download_requires_the_file_param(client, finished, login):
    assert _download(client, finished, token=login()).status_code == 400


def test_download_of_a_job_without_output_is_404(
    client, user_factory, job_factory, login
):
    user_factory("alice")
    job_factory("no-output", "alice")
    resp = _download(client, "no-output", token=login(), file="notes_csv_file")
    assert resp.status_code == 404


@pytest.mark.parametrize("share_token", ["tok-file", "tok-all"])
def test_the_archive_and_job_wide_links_may_download(client, finished, share_token):
    resp = _download(client, finished, share_token=share_token, file="notes_csv_file")
    assert resp.status_code == 200
    assert resp.data.startswith(b"Matricule")


def test_the_share_url_itself_downloads_with_its_token_param(client, finished):
    # the url built by /file/share carries the link in "token", not "share_token"
    resp = _download(client, finished, token="tok-file", file="zip_file", zip_index="1")
    assert resp.status_code == 200
    assert resp.data == b"ZIP1"


@pytest.mark.parametrize("share_token", ["tok-q", "tok-mat", "garbage"])
def test_question_and_matricule_links_cannot_download(client, finished, share_token):
    resp = _download(client, finished, share_token=share_token, file="notes_csv_file")
    assert resp.status_code == 401
    assert b"Matricule" not in resp.data


def test_the_link_of_one_job_does_not_open_another(
    client, finished, job_factory, app_module_fixture
):
    job_factory("other", "alice", share_token={"all": "tok-other"})
    app_module_fixture.mongo["RMN"]["jobs_output"].insert_one(
        {"job_id": "other", "user_id": "alice", "share_token": "tok-other-file"}
    )
    for token in ("tok-other", "tok-other-file"):
        resp = _download(client, finished, share_token=token, file="notes_csv_file")
        assert resp.status_code == 401


def test_another_user_cannot_download(client, finished, user_factory, login):
    user_factory("bob")
    resp = _download(client, finished, token=login("bob"), file="notes_csv_file")
    assert resp.status_code == 401
    assert b"Matricule" not in resp.data


# ------------------------------------------------------------- share link ---
def _share(client, job_id, host="rmn.example.org", **data):
    return client.post(
        "/files/share", data={"job_id": job_id, **data}, headers={"Host": host}
    )


def test_share_returns_the_existing_archive_link(client, finished, login):
    resp = _share(client, finished, token=login(), file="notes_csv_file")
    assert resp.status_code == 200, resp.data
    body = resp.get_json(force=True)["response"]
    assert body == {
        "job_id": finished,
        "share_url": f"https://rmn.example.org/api/file/download?job_id={finished}"
        "&token=tok-file&file=notes_csv_file",
    }


def test_share_of_a_zip_carries_its_index(client, finished, login):
    resp = _share(client, finished, token=login(), file="zip_file", zip_index="1")
    url = resp.get_json(force=True)["response"]["share_url"]
    assert url.endswith("&file=zip_file&zip_index=1")
    assert _share(client, finished, token=login(), file="zip_file").status_code == 400


def test_share_creates_the_archive_token_on_first_use(
    client, user_factory, job_factory, login, app_module_fixture
):
    user_factory("alice")
    job_factory("fresh", "alice")
    outputs = app_module_fixture.mongo["RMN"]["jobs_output"]
    outputs.insert_one({"job_id": "fresh", "user_id": "alice", "zip_id_list": []})

    resp = _share(client, "fresh", token=login(), file="notes_csv_file")

    assert resp.status_code == 200
    token = outputs.find_one({"job_id": "fresh"})["share_token"]
    assert (
        token
        and f"&token={token}&" in resp.get_json(force=True)["response"]["share_url"]
    )


def test_share_of_a_job_without_output_is_404(client, user_factory, job_factory, login):
    user_factory("alice")
    job_factory("no-output", "alice")
    resp = _share(client, "no-output", token=login(), file="notes_csv_file")
    assert resp.status_code == 404


def test_share_requires_the_file_and_a_host(client, finished, login):
    token = login()
    assert _share(client, finished, token=token).status_code == 400
    assert _share(client, finished, host="", token=token, file="x").status_code == 400


def test_a_question_link_cannot_share_the_archive(client, finished):
    resp = _share(client, finished, share_token="tok-q", file="notes_csv_file")
    assert resp.status_code == 401


def test_another_user_cannot_share_the_archive(client, finished, user_factory, login):
    user_factory("bob")
    resp = _share(client, finished, token=login("bob"), file="notes_csv_file")
    assert resp.status_code == 401


def test_unshare_revokes_the_archive_link(client, finished, login, app_module_fixture):
    resp = client.post("/files/unshare", data={"job_id": finished, "token": login()})

    assert resp.status_code == 200
    stored = app_module_fixture.mongo["RMN"]["jobs_output"].find_one(
        {"job_id": finished}
    )
    assert "share_token" not in stored
    resp = _download(client, finished, share_token="tok-file", file="notes_csv_file")
    assert resp.status_code == 401


def test_another_user_cannot_unshare_the_archive(
    client, finished, user_factory, login, app_module_fixture
):
    user_factory("bob")
    resp = client.post(
        "/files/unshare", data={"job_id": finished, "token": login("bob")}
    )
    assert resp.status_code == 404
    stored = app_module_fixture.mongo["RMN"]["jobs_output"].find_one(
        {"job_id": finished}
    )
    assert stored["share_token"] == "tok-file"


def test_unshare_requires_a_job_id(client, finished, login):
    assert client.post("/files/unshare", data={"token": login()}).status_code == 400


@pytest.mark.parametrize("index", ["2", "-1"])
def test_a_zip_index_out_of_range_is_404(client, finished, login, index):
    # an IndexError (a 500) past the end; -1 used to serve the last archive
    resp = _download(client, finished, token=login(), file="zip_file", zip_index=index)
    assert resp.status_code == 404, resp.data
    assert resp.get_json(force=True) == {"response": f"Error: zip {index} doesn't exist."}


def test_a_malformed_zip_index_is_400(client, finished, login):
    resp = _download(client, finished, token=login(), file="zip_file", zip_index="a")
    assert resp.status_code == 400, resp.data
    assert resp.get_json(force=True) == {"response": "Error: zip_index is not a number."}


@pytest.mark.parametrize(
    "file,field", [("stats_pdf_file", "stats_file_id"), ("zip_file", "zip_id_list")]
)
def test_an_output_not_written_yet_is_404(
    client, finished, login, app_module_fixture, file, field
):
    # the executor had not stored it yet: a KeyError, a 500
    app_module_fixture.mongo["RMN"]["jobs_output"].update_one(
        {"job_id": finished}, {"$unset": {field: ""}}
    )
    resp = _download(client, finished, token=login(), file=file, zip_index="0")
    assert resp.status_code == 404, resp.data
