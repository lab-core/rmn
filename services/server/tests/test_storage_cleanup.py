"""The storage sweep: what it removes, what it must never touch."""

import datetime as dt
import os
import time

import pytest

from service import storage_cleanup
from routes import admin as admin_routes

HEADERS = {"X-Admin-Key": "test-admin-key"}


@pytest.fixture
def tree(tmp_path, monkeypatch, app_module_fixture):
    """A storage tree of its own; yields ``(storage, db, write)``.

    The suite shares one storage root, and a sweep looks at the whole tree:
    these tests get their own root so that files another test left behind
    cannot show up in the report.
    """
    storage = type(app_module_fixture.storage)(tmp_path)
    monkeypatch.setattr(admin_routes, "storage", storage)
    db = app_module_fixture.mongo["RMN"]

    def write(relative, age_seconds=48 * 3600):
        path = storage.abs_path(relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"x")
        old = time.time() - age_seconds
        os.utime(path, (old, old))
        # a directory's own mtime is what the age guard reads
        os.utime(os.path.dirname(path), (old, old))
        return path

    return storage, db, write


def test_orphan_job_files_are_found_and_deleted(tree):
    storage, db, write = tree
    db["eval_jobs"].insert_one({"job_id": "live", "user_id": "alice"})
    kept = write("documents/live/1.png")
    gone_dir = write("documents/dead/1.png")
    gone_csv = write("csv/dead.csv")
    gone_zip = write("output_zip/dead_all.zip")

    report = storage_cleanup.clean(storage, db)

    assert sorted(report["deleted"]) == sorted(
        [os.path.dirname(gone_dir), gone_csv, gone_zip]
    )
    assert os.path.exists(kept)
    assert not os.path.exists(gone_csv)


def test_orphan_templates_are_found_by_their_stored_path(tree):
    storage, db, write = tree
    db["template"].insert_one(
        {"template_id": "t1", "template_file_id": "template/t1.png"}
    )
    kept = write("template/t1.png")
    orphan = write("template/t2.png")

    report = storage_cleanup.clean(storage, db)

    assert report["deleted"] == [orphan]
    assert os.path.exists(kept)


def test_the_digit_corpus_is_never_swept(tree):
    """``numbers/`` belongs to no row; a sweep that removed it would be a loss."""
    storage, db, write = tree
    corpus = write("numbers/7/abcd.png")

    report = storage_cleanup.clean(storage, db, include_strays=True)

    assert report["deleted"] == [] and os.path.exists(corpus)


def test_recent_paths_are_left_for_the_next_sweep(tree):
    """A template image is stored just before its row: never sweep a fresh one."""
    storage, db, write = tree
    fresh = write("template/new.png", age_seconds=60)

    report = storage_cleanup.scan(storage, db)

    assert report["orphans"] == [] and report["too_recent"] == 1
    assert os.path.exists(fresh)


def test_strays_are_reported_but_kept_unless_asked(tree):
    storage, db, write = tree
    stray = write("documents/loose.png")

    report = storage_cleanup.clean(storage, db)
    assert [s["path"] for s in report["strays"]] == [stray]
    assert report["deleted"] == [] and os.path.exists(stray)

    report = storage_cleanup.clean(storage, db, include_strays=True)
    assert report["deleted"] == [stray] and not os.path.exists(stray)


def test_rows_pointing_at_a_missing_image_are_reported(tree):
    storage, db, _ = tree
    db["template"].insert_one(
        {"template_id": "t1", "template_file_id": "template/gone.png"}
    )
    assert storage_cleanup.scan(storage, db)["missing"] == ["template/gone.png"]


def _job(db, job_id, age_seconds=48 * 3600, **fields):
    """Insert an ``eval_jobs`` row queued ``age_seconds`` ago, plus a document."""
    queued = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=age_seconds)
    db["eval_jobs"].insert_one(
        {
            "job_id": job_id,
            "user_id": "alice",
            "job_name": job_id,
            "job_status": "VALIDATION",
            "queued_time": queued,
            **fields,
        }
    )
    db["job_documents"].insert_one({"job_id": job_id, "document_index": 0})


def test_jobs_without_any_file_are_reported_but_kept(tree):
    storage, db, write = tree
    _job(db, "kept")
    write("output_csv/kept.csv")  # a single stored path is enough
    _job(db, "empty")

    report = storage_cleanup.clean(storage, db)

    assert [j["job_id"] for j in report["empty_jobs"]] == ["empty"]
    assert report["empty_jobs"][0]["user_id"] == "alice"
    assert report["deleted_jobs"] == []
    assert db["eval_jobs"].count_documents({"job_id": "empty"}) == 1


def test_jobs_without_any_file_are_deleted_when_asked(tree):
    storage, db, write = tree
    _job(db, "kept")
    write("documents/kept/1.png")
    _job(db, "empty")
    deleted = []

    report = storage_cleanup.clean(storage, db, delete_job=deleted.append)

    assert report["deleted_jobs"] == deleted == ["empty"]


def test_a_job_being_created_is_not_empty_yet(tree):
    """The row is inserted just before the upload is stored."""
    storage, db, _ = tree
    _job(db, "uploading", age_seconds=60)

    assert storage_cleanup.scan(storage, db)["empty_jobs"] == []
    assert storage_cleanup.scan(storage, db, min_age_seconds=0)["empty_jobs"]


def test_a_legacy_row_without_queued_time_counts_as_old(tree):
    storage, db, _ = tree
    db["eval_jobs"].insert_one({"job_id": "legacy"})

    (entry,) = storage_cleanup.scan(storage, db)["empty_jobs"]
    assert entry["job_id"] == "legacy" and entry["age_seconds"] is None


def test_a_failing_job_delete_is_reported(tree):
    storage, db, _ = tree
    _job(db, "empty")

    def boom(job_id):
        raise RuntimeError("mongo down")

    report = storage_cleanup.clean(storage, db, delete_job=boom)

    assert report["deleted_jobs"] == []
    assert report["failed"] == [{"job_id": "empty", "error": "mongo down"}]


def test_admin_endpoint_deletes_empty_jobs_only_when_asked(client, tree):
    storage, db, _ = tree
    _job(db, "empty")

    body = client.post(
        "/admin/storage/clean", data={"dry_run": "false"}, headers=HEADERS
    ).get_json(force=True)
    assert [j["job_id"] for j in body["empty_jobs"]] == ["empty"]
    assert body["deleted_jobs"] == []
    assert db["eval_jobs"].count_documents({"job_id": "empty"}) == 1

    body = client.post(
        "/admin/storage/clean",
        data={"dry_run": "false", "include_empty_jobs": "true"},
        headers=HEADERS,
    ).get_json(force=True)
    assert body["deleted_jobs"] == ["empty"]
    # the whole job goes, not only its eval_jobs row
    assert db["eval_jobs"].count_documents({"job_id": "empty"}) == 0
    assert db["job_documents"].count_documents({"job_id": "empty"}) == 0


def test_admin_endpoint_never_deletes_empty_jobs_on_a_dry_run(client, tree):
    storage, db, _ = tree
    _job(db, "empty")

    body = client.post(
        "/admin/storage/clean", data={"include_empty_jobs": "true"}, headers=HEADERS
    ).get_json(force=True)
    assert body["dry_run"] is True and "deleted_jobs" not in body
    assert db["eval_jobs"].count_documents({"job_id": "empty"}) == 1


def test_admin_endpoint_reports_without_deleting_by_default(client, tree):
    storage, db, write = tree
    orphan = write("csv/dead.csv")

    resp = client.post("/admin/storage/clean", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.get_json(force=True)
    assert body["response"] == "OK" and body["dry_run"] is True
    assert [o["path"] for o in body["orphans"]] == [orphan]
    assert "deleted" not in body and os.path.exists(orphan)


def test_admin_endpoint_deletes_when_asked(client, tree):
    storage, db, write = tree
    orphan = write("csv/dead.csv")

    resp = client.post(
        "/admin/storage/clean",
        data={"dry_run": "false", "min_age_hours": "1"},
        headers=HEADERS,
    )

    body = resp.get_json(force=True)
    assert body["deleted"] == [orphan] and not os.path.exists(orphan)


def test_admin_endpoint_rejects_a_bad_age_and_the_wrong_key(client):
    resp = client.post(
        "/admin/storage/clean", data={"min_age_hours": "soon"}, headers=HEADERS
    )
    assert resp.status_code == 400
    resp = client.post("/admin/storage/clean", headers={"X-Admin-Key": "nope"})
    assert resp.status_code == 403


def test_usage_buckets_are_cumulative_by_age(tree):
    storage, db, write = tree
    day = 24 * 3600
    write("documents/a/new.png", age_seconds=0)
    write("documents/b/month.png", age_seconds=40 * day)
    write("numbers/0/old.png", age_seconds=400 * day)

    usage = storage_cleanup.usage(storage)

    files = {days: b["files"] for days, b in usage["older_than_days"].items()}
    assert files == {"0": 3, "30": 2, "90": 1, "180": 1, "365": 1}
    assert usage["older_than_days"]["0"]["bytes"] == 3
    assert usage["disk"]["total"] >= usage["disk"]["used"] > 0


def test_usage_skips_symlinks(tree):
    storage, db, write = tree
    target = write("documents/a/1.png")
    os.symlink(target, storage.abs_path("documents/a/link.png"))

    assert storage_cleanup.usage(storage)["older_than_days"]["0"]["files"] == 1


def test_admin_endpoint_adds_usage_only_when_asked(client, tree):
    storage, db, write = tree
    write("documents/a/1.png")

    body = client.post("/admin/storage/clean", headers=HEADERS).get_json(force=True)
    assert "usage" not in body
    body = client.post(
        "/admin/storage/clean", data={"usage": "true"}, headers=HEADERS
    ).get_json(force=True)
    assert body["usage"]["older_than_days"]["0"]["files"] == 1
