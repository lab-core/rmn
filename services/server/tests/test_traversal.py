"""Path-traversal protection on the file endpoints."""

import io
import os
import zipfile


def _abs(app_module, *parts):
    return app_module.storage.abs_path(os.path.join(*parts))


def test_incorrect_download_blocks_traversal(client, user_factory, job_factory, login, app_module_fixture):
    user_factory("alice")
    job_factory("job1", owner="alice")
    token = login("alice")

    # plant a secret outside the job directory
    secret = os.path.join(str(app_module_fixture.storage.path), "secret.txt")
    with open(secret, "w") as f:
        f.write("TOP SECRET")

    resp = client.post(
        "/jobs/incorrect/download",
        data={"user_id": "alice", "token": token, "job_id": "job1", "file": "../../secret.txt"},
    )
    assert resp.status_code == 404
    assert b"TOP SECRET" not in resp.data


def test_incorrect_download_owner_gets_real_file(client, user_factory, job_factory, login, app_module_fixture):
    user_factory("alice")
    job_factory("job1", owner="alice")
    token = login("alice")

    job_dir = _abs(app_module_fixture, "incorrect_files", "job1")
    os.makedirs(job_dir, exist_ok=True)
    with open(os.path.join(job_dir, "Etudiant_1.pdf"), "wb") as f:
        f.write(b"REAL PDF BYTES")

    resp = client.post(
        "/jobs/incorrect/download",
        data={"user_id": "alice", "token": token, "job_id": "job1", "file": "Etudiant_1.pdf"},
    )
    assert resp.status_code == 200
    assert resp.data == b"REAL PDF BYTES"


def test_incorrect_download_foreign_user_blocked(client, user_factory, job_factory, login, app_module_fixture):
    user_factory("alice")
    user_factory("bob")
    job_factory("job1", owner="alice")

    job_dir = _abs(app_module_fixture, "incorrect_files", "job1")
    os.makedirs(job_dir, exist_ok=True)
    with open(os.path.join(job_dir, "Etudiant_1.pdf"), "wb") as f:
        f.write(b"REAL PDF BYTES")

    bob_token = login("bob")
    resp = client.post(
        "/jobs/incorrect/download",
        data={"user_id": "bob", "token": bob_token, "job_id": "job1", "file": "Etudiant_1.pdf"},
    )
    assert resp.status_code == 404


def test_continue_sanitizes_uploaded_filename(client, user_factory, job_factory, login, app_module_fixture):
    user_factory("alice")
    job_factory("job1", owner="alice", status="VALIDATION")
    token = login("alice")

    # the endpoint writes into zips/<job_id>/, which must already exist
    os.makedirs(_abs(app_module_fixture, "zips", "job1"), exist_ok=True)

    resp = client.post(
        "/jobs/continue",
        data={
            "user_id": "alice",
            "token": token,
            "job_id": "job1",
            "file": (io.BytesIO(b"%PDF-1.4\n"), "../../../../evil.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200

    # nothing escaped the storage root
    assert not os.path.exists(os.path.join(str(app_module_fixture.storage.path), "evil.pdf"))

    # the archive member name was flattened (no traversal, no separators)
    zips = [
        f for f in os.listdir(_abs(app_module_fixture, "zips", "job1")) if f.endswith(".zip")
    ]
    assert zips
    for z in zips:
        with zipfile.ZipFile(_abs(app_module_fixture, "zips", "job1", z)) as zf:
            for name in zf.namelist():
                assert ".." not in name
                assert "/" not in name and "\\" not in name
