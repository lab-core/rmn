"""Find and delete storage that no database row owns any more.

A job's files are written after its ``eval_jobs`` row exists and are deleted
with it (``delete_job``), so the tree and the database normally agree. They
drift when a delete is interrupted: the executor pod is evicted mid-write,
the NFS share is unreachable while Mongo is not, a job is dropped straight
from the database. What is left behind is invisible to the application and
keeps filling the share.

Ownership is read from the layout tables of ``rmn_common.storage``: a path is
an orphan only when it is shaped like a job's or a template's and the id in
its name has no row. Everything else in the tree is left alone -- in
particular ``rmn_common.storage.CORPUS_DIRS``, the digits kept to retrain the
recogniser (``digit_bank/samples`` and the older ``numbers/``), which no row
owns and which this module must never delete. The usage summary counts them
on their own line, because they are the one part of the share that only
grows.

Two things make the sweep safe to run on a live system:

* a template image is moved into the tree just before its row is inserted, so
  a sweep racing an upload could see it unowned. Nothing younger than
  ``min_age_seconds`` is considered (a day by default).
* deleting is opt-in: the scan reports, the caller decides.

The other direction is reported too: ``eval_jobs`` rows none of whose paths
exist any more (``empty_jobs``). Such a job cannot be opened, corrected or
downloaded; its rows are removed only when the caller passes ``delete_job``
to ``clean``. A row is written just before its upload, so the same age guard
applies, on ``queued_time``.
"""

import datetime as dt
import os
import shutil
import stat
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

DEFAULT_MIN_AGE_SECONDS = 24 * 3600
# age thresholds of the disk usage summary, in days (0 = everything)
USAGE_AGE_DAYS = (0, 30, 90, 180, 365)


def scan(storage: Any, db: Any, min_age_seconds: int = DEFAULT_MIN_AGE_SECONDS) -> Dict:
    """Report the storage paths no database row owns.

    Args:
        storage: The ``Storage`` whose tree is scanned.
        db: The ``RMN`` Mongo database.
        min_age_seconds: Ignore paths modified more recently than this, so a
            sweep cannot race an upload in progress. 0 disables the guard.

    Returns:
        A report ``{"orphans": [...], "strays": [...], "missing": [...],
        "empty_jobs": [...], "bytes": int, "scanned": {...}}``. ``orphans``
        are paths whose owner is gone, each ``{"path", "reason", "owner",
        "bytes", "age_seconds"}``; ``strays`` are paths under a known prefix
        that match no layout rule; ``missing`` are template rows pointing at a
        path that no longer exists; ``empty_jobs`` are ``eval_jobs`` rows with
        no stored path at all, each ``{"job_id", "user_id", "job_name",
        "job_status", "age_seconds"}``.
    """
    jobs = list(
        db["eval_jobs"].find(
            {},
            {
                "job_id": 1,
                "user_id": 1,
                "job_name": 1,
                "job_status": 1,
                "queued_time": 1,
            },
        )
    )
    job_ids = {job["job_id"] for job in jobs}
    templates = {
        template["template_file_id"]
        for template in db["template"].find({}, {"template_file_id": 1})
        if template.get("template_file_id")
    }

    now = time.time()
    orphans: List[Dict] = []
    seen = {"jobs": 0, "templates": 0}
    stored_job_ids = set()

    for job_id, path in storage.job_entries():
        seen["jobs"] += 1
        stored_job_ids.add(job_id)
        if job_id not in job_ids:
            orphans.append(_entry(path, "no eval_jobs row", job_id, now))

    for relative, path in storage.template_entries():
        seen["templates"] += 1
        if relative not in templates:
            orphans.append(_entry(path, "no template row", relative, now))

    strays = [
        _entry(path, "not in the storage layout", None, now)
        for path in storage.stray_entries()
    ]

    kept = [o for o in orphans if o["age_seconds"] < min_age_seconds]
    orphans = [o for o in orphans if o["age_seconds"] >= min_age_seconds]
    strays = [s for s in strays if s["age_seconds"] >= min_age_seconds]
    empty_jobs = [
        entry
        for entry in (
            _empty_job(job, now) for job in jobs if job["job_id"] not in stored_job_ids
        )
        if entry["age_seconds"] is None or entry["age_seconds"] >= min_age_seconds
    ]

    return {
        "orphans": sorted(orphans, key=lambda o: o["path"]),
        "strays": sorted(strays, key=lambda s: s["path"]),
        "missing": sorted(_missing(storage, templates)),
        "empty_jobs": sorted(empty_jobs, key=lambda j: j["job_id"]),
        "too_recent": len(kept),
        "bytes": sum(o["bytes"] for o in orphans),
        "scanned": seen,
    }


def clean(
    storage: Any,
    db: Any,
    min_age_seconds: int = DEFAULT_MIN_AGE_SECONDS,
    include_strays: bool = False,
    delete_job: Optional[Callable[[str], None]] = None,
) -> Dict:
    """Scan, then delete what the scan found.

    Args:
        storage: The ``Storage`` whose tree is swept.
        db: The ``RMN`` Mongo database.
        min_age_seconds: See ``scan``.
        include_strays: Also delete the paths that match no layout rule. Off
            by default: an unnamed path may be a layout this code does not
            know about yet rather than garbage.
        delete_job: Also remove the ``empty_jobs`` rows, by calling this with
            each job id (the server's ``job_cleanup.delete_job``, so every
            collection and queued reference of the job goes with it). Off by
            default.

    Returns:
        The scan report with ``deleted`` (paths removed), ``deleted_jobs``
        (job ids removed) and ``failed`` (``{"path" | "job_id", "error"}``)
        added.
    """
    report = scan(storage, db, min_age_seconds)
    targets = report["orphans"] + (report["strays"] if include_strays else [])

    deleted, failed = [], []
    for entry in targets:
        try:
            _remove(entry["path"])
            deleted.append(entry["path"])
        except OSError as e:
            failed.append({"path": entry["path"], "error": str(e)})

    deleted_jobs = []
    for entry in report["empty_jobs"] if delete_job else []:
        try:
            delete_job(entry["job_id"])
            deleted_jobs.append(entry["job_id"])
        except Exception as e:
            failed.append({"job_id": entry["job_id"], "error": str(e)})
    report["deleted"] = deleted
    report["deleted_jobs"] = deleted_jobs
    report["failed"] = failed
    return report


def usage(storage: Any, age_days: Iterable[int] = USAGE_AGE_DAYS) -> Dict:
    """Summarise how much of the share is used, and by how old files.

    Every regular file under the storage root is counted once per threshold
    it is older than (by modification time), so the buckets are cumulative:
    ``older_than_days["30"]`` includes ``older_than_days["90"]``. Symlinks are
    not followed. The whole tree is walked, ``numbers/`` included: this is
    about disk space, not ownership.

    Args:
        storage: The ``Storage`` whose tree is measured.
        age_days: The thresholds, in days.

    Returns:
        ``{"older_than_days": {"<days>": {"bytes", "files"}}, "corpus":
        {"<dir>": {"bytes", "files"}}, "disk": {"total", "used", "free"}}``.
        ``corpus`` is the training data of ``CORPUS_DIRS``, counted on its own
        because no cleanup ever removes it; those files are in the age buckets
        too, which measure the whole share. ``disk`` is the filesystem holding
        the root (bytes, from ``statvfs``), ``None`` when it cannot be read.
    """
    now = time.time()
    thresholds = sorted(set(age_days))
    buckets = {str(days): {"bytes": 0, "files": 0} for days in thresholds}
    for root, _, files in os.walk(storage.path):
        for name in files:
            try:
                info = os.lstat(os.path.join(root, name))
            except OSError:
                continue  # removed while walking
            if not stat.S_ISREG(info.st_mode):
                continue
            age = now - info.st_mtime
            for days in thresholds:
                if age < days * 86400:
                    break
                buckets[str(days)]["bytes"] += info.st_size
                buckets[str(days)]["files"] += 1

    try:
        fs = os.statvfs(storage.path)
        disk = {
            "total": fs.f_blocks * fs.f_frsize,
            "used": (fs.f_blocks - fs.f_bfree) * fs.f_frsize,
            "free": fs.f_bavail * fs.f_frsize,
        }
    except OSError:
        disk = None
    return {"older_than_days": buckets, "corpus": storage.corpus_usage(), "disk": disk}


def _entry(path: str, reason: str, owner: Optional[str], now: float) -> Dict:
    """Describe one path for the report."""
    try:
        age = max(now - os.path.getmtime(path), 0)
    except OSError:
        age = 0
    return {
        "path": path,
        "reason": reason,
        "owner": owner,
        "bytes": _size(path),
        "age_seconds": int(age),
    }


def _empty_job(job: Dict, now: float) -> Dict:
    """Describe one job row without stored data for the report.

    ``age_seconds`` is ``None`` for a row without ``queued_time``, which only
    rows predating that field lack: such a row is not being created now.
    """
    queued = job.get("queued_time")
    age = None
    if isinstance(queued, dt.datetime):
        # pymongo hands back naive datetimes, in UTC
        if queued.tzinfo is None:
            queued = queued.replace(tzinfo=dt.UTC)
        age = int(max(now - queued.timestamp(), 0))
    return {
        "job_id": job["job_id"],
        "user_id": job.get("user_id"),
        "job_name": job.get("job_name"),
        "job_status": job.get("job_status"),
        "age_seconds": age,
    }


def _size(path: str) -> int:
    """Bytes held by a file or, recursively, by a directory."""
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _remove(path: str) -> None:
    """Delete a file or a whole directory."""
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def _missing(storage: Any, templates: Iterable[str]) -> List[str]:
    """Template rows whose image is gone (reported, never repaired here)."""
    return [
        relative
        for relative in templates
        if not os.path.exists(storage.abs_path(relative))
    ]
