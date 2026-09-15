"""The shared storage tree (an NFS share in the cluster) and its per-job layout.

Both services read and write the same tree; the layout below is the single
description of what belongs to a job, so deleting a job removes the same
paths on both sides.
"""

import glob
import os
import shutil
from pathlib import Path


def create_tree(file_path):
    """Create the parent directories of ``file_path``."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)


def move(old_file, new_file):
    """Move across filesystems (``shutil.move`` fails with EXDEV on the NFS share)."""
    shutil.copy(old_file, new_file)
    os.remove(old_file)


class Storage:
    """Paths under the storage root, moves, copies and per-job cleanup.

    The root is, in order: the ``storage_path`` argument, the ``STORAGE``
    environment variable, then ``default_path`` (each service sets it to
    ``<service root>/storage`` in its own subclass).
    """

    default_path = None

    # Per-job storage layout: directories named <prefix>/<job_id> and files
    # named after the job. remove_job deletes exactly these paths.
    _JOB_DIRS = (
        "documents",
        "cover_pages",
        "corrected_copies",
        "incorrect_files",
        "zips",
        "unverified_numbers",
    )
    _JOB_FILES = (
        ("csv", "{job_id}.csv"),
        ("output_csv", "{job_id}.csv"),
        ("output_stats", "{job_id}.pdf"),
        ("zips", "{job_id}.zip"),  # legacy single-zip layout
    )
    # files whose name starts with the job id (e.g. output_zip/<job_id>_all.zip)
    _JOB_GLOBS = (("output_zip", "{job_id}_*.zip"),)

    def __init__(self, storage_path=None):
        if storage_path:
            self.path = Path(storage_path)
        elif os.getenv("STORAGE"):
            self.path = Path(os.getenv("STORAGE"))
        elif self.default_path is not None:
            self.path = Path(self.default_path)
        else:
            raise ValueError("STORAGE is not set and this Storage has no default path")

    def abs_path(self, r_path):
        """Absolute path of a storage-relative path.

        An absolute input is accepted when it already lies under the root
        (callers hand back paths this method returned). Anything that would
        resolve outside the root, a ``..`` component or a foreign absolute
        path, raises ``ValueError``: every read and write of the tree goes
        through here, so this is the one containment check for all of them.
        """
        joined = os.path.join(str(self.path), str(r_path))
        root = os.path.realpath(self.path)
        resolved = os.path.realpath(joined)
        if resolved != root and not resolved.startswith(root + os.sep):
            raise ValueError(f"path escapes the storage root: {r_path}")
        return joined

    def rel_path(self, abs_path):
        """Storage-relative path of an absolute path under the root."""
        if not os.path.isabs(abs_path):
            return abs_path
        try:
            return str(Path(abs_path).relative_to(self.path))
        except ValueError:
            path_split = abs_path.split("storage/")
            if len(path_split) > 1:
                return path_split[1]
            return abs_path

    def move_to(self, l_file, s_file):
        """Move a local file into the storage; returns the absolute destination."""
        s_abs_file = self.abs_path(s_file)
        if not os.path.exists(l_file):
            raise ValueError("Storage can't find local file " + l_file)
        create_tree(s_abs_file)
        move(l_file, s_abs_file)
        return s_abs_file

    def copy_from(self, s_file, l_file):
        """Copy a stored file to a local path; returns that path."""
        s_abs_file = self.abs_path(s_file)
        if not os.path.exists(s_abs_file):
            raise ValueError("Storage can't find file " + s_abs_file)
        create_tree(l_file)
        shutil.copy(s_abs_file, l_file)
        return l_file

    def remove(self, s_file):
        """Remove the stored file(s) matching ``s_file`` (a glob); missing is fine."""
        for f in glob.glob(str(self.abs_path(s_file))):
            os.remove(f)

    def remove_tree(self, s_dir):
        shutil.rmtree(self.abs_path(s_dir), ignore_errors=True)

    def remove_job(self, job_id):
        """Delete all storage belonging to a single job, by its known paths.

        O(one job) rather than walking the whole (NFS-backed) tree like
        ``remove_all_match``, which made every delete scan every job's files.
        """
        for prefix in self._JOB_DIRS:
            shutil.rmtree(
                self.abs_path(os.path.join(prefix, job_id)), ignore_errors=True
            )

        for prefix, name in self._JOB_FILES:
            try:
                os.remove(
                    self.abs_path(os.path.join(prefix, name.format(job_id=job_id)))
                )
            except OSError:
                pass

        for prefix, pattern in self._JOB_GLOBS:
            for f in glob.glob(
                self.abs_path(os.path.join(prefix, pattern.format(job_id=job_id)))
            ):
                try:
                    os.remove(f)
                except OSError:
                    pass

    def remove_all_match(self, key):
        """Remove every file or directory whose name contains ``key``.

        Walks the ENTIRE storage tree; prefer ``remove_job`` for a single job.
        """
        files_to_delete = []
        dirs_to_delete = []
        for root, dirs, files in os.walk(str(self.path)):
            files_to_delete += [os.path.join(root, f) for f in files if key in f]
            dirs_to_delete += [os.path.join(root, d) for d in dirs if key in d]
        for f in files_to_delete:
            try:
                os.remove(f)
            except OSError:
                pass
        for d in dirs_to_delete:
            shutil.rmtree(d, ignore_errors=True)
