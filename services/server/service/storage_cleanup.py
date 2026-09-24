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
particular ``numbers/``, the shared digit corpus, which no row owns.

Two things make the sweep safe to run on a live system:

* a template image is moved into the tree just before its row is inserted, so
  a sweep racing an upload could see it unowned. Nothing younger than
  ``min_age_seconds`` is considered (a day by default).
* deleting is opt-in: the scan reports, the caller decides.
"""

import os
import shutil
import time
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_MIN_AGE_SECONDS = 24 * 3600


def scan(storage: Any, db: Any, min_age_seconds: int = DEFAULT_MIN_AGE_SECONDS) -> Dict:
    """Report the storage paths no database row owns.

    Args:
        storage: The ``Storage`` whose tree is scanned.
        db: The ``RMN`` Mongo database.
        min_age_seconds: Ignore paths modified more recently than this, so a
            sweep cannot race an upload in progress. 0 disables the guard.

    Returns:
        A report ``{"orphans": [...], "strays": [...], "missing": [...],
        "bytes": int, "scanned": {...}}``. ``orphans`` are paths whose owner
        is gone, each ``{"path", "reason", "owner", "bytes", "age_seconds"}``;
        ``strays`` are paths under a known prefix that match no layout rule;
        ``missing`` are rows pointing at a path that no longer exists. Only
        ``orphans`` are deleted by ``clean``.
    """
    job_ids = {job["job_id"] for job in db["eval_jobs"].find({}, {"job_id": 1})}
    templates = {
        template["template_file_id"]
        for template in db["template"].find({}, {"template_file_id": 1})
        if template.get("template_file_id")
    }

    now = time.time()
    orphans: List[Dict] = []
    seen = {"jobs": 0, "templates": 0}

    for job_id, path in storage.job_entries():
        seen["jobs"] += 1
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

    return {
        "orphans": sorted(orphans, key=lambda o: o["path"]),
        "strays": sorted(strays, key=lambda s: s["path"]),
        "missing": sorted(_missing(storage, templates)),
        "too_recent": len(kept),
        "bytes": sum(o["bytes"] for o in orphans),
        "scanned": seen,
    }


def clean(
    storage: Any,
    db: Any,
    min_age_seconds: int = DEFAULT_MIN_AGE_SECONDS,
    include_strays: bool = False,
) -> Dict:
    """Scan, then delete what the scan found.

    Args:
        storage: The ``Storage`` whose tree is swept.
        db: The ``RMN`` Mongo database.
        min_age_seconds: See ``scan``.
        include_strays: Also delete the paths that match no layout rule. Off
            by default: an unnamed path may be a layout this code does not
            know about yet rather than garbage.

    Returns:
        The scan report with ``deleted`` (paths removed) and ``failed``
        (``{"path", "error"}``) added.
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
    report["deleted"] = deleted
    report["failed"] = failed
    return report


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
