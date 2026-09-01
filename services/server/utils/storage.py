import os
import shutil
import glob
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


def create_tree(file_path):
    os.makedirs(file_path.rsplit(os.sep, 1)[0], exist_ok=True)


# use this method to avoid Invalid cross-device link error
# https://stackoverflow.com/questions/42392600/oserror-errno-18-invalid-cross-device-link
# shutil.move() seems to not detect the different filesystem
def move(old_file, new_file):
    shutil.copy(old_file, new_file)
    os.remove(old_file)


class Storage:
    def __init__(self, storage_path=None):
        if storage_path:
            self.path = Path(storage_path)
            print("Storage path:", self.path)
        elif os.getenv('STORAGE'):
            self.path = Path(os.getenv('STORAGE')).resolve()
        else:
            self.path = ROOT_DIR.joinpath("storage")
        print(f"Access for {self.path}: ", os.access(self.path, os.R_OK))
        print(f"Access for {self.path}: ", os.access(self.path, os.W_OK))

    def abs_path(self, r_path):
        if os.path.isabs(r_path):
            return r_path
        abs_path = str(self.path.joinpath(r_path))
        return abs_path

    def rel_path(self, abs_path):
        if not os.path.isabs(abs_path):
            return abs_path
        try:
            rel_path = str(Path(abs_path).relative_to(self.path))
            return rel_path
        except ValueError:
            path_split = abs_path.split("storage/")
            if len(path_split) > 1:
                return path_split[1]
            return abs_path

    def move_to(self, l_file, s_file):
        s_abs_file = self.abs_path(s_file)
        if not os.path.exists(l_file):
            raise ValueError("Storage can't find local file " + l_file)
        create_tree(s_abs_file)
        move(l_file, s_abs_file)
        return s_abs_file

    def copy_from(self, s_file, l_file):
        s_abs_file = self.abs_path(s_file)
        if not os.path.exists(s_abs_file):
            raise ValueError("Storage can't find file " + s_abs_file)
        create_tree(l_file)
        shutil.copy(s_abs_file, l_file)
        return l_file

    def remove(self, s_file):
        abs_path = self.abs_path(s_file)
        for f in glob.glob(str(abs_path)):
            os.remove(f)

    def remove_tree(self, s_dir):
        shutil.rmtree(self.abs_path(s_dir), ignore_errors=True)

    # Per-job storage layout: directories named <prefix>/<job_id> and files
    # named after the job. Kept here so remove_job stays in sync with writers.
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
    _JOB_GLOBS = (
        ("output_zip", "{job_id}_*.zip"),
    )

    def remove_job(self, job_id):
        """Delete all storage belonging to a single job.

        Only the known per-job paths are removed, so this is O(one job) rather
        than walking the whole (NFS-backed) storage tree like remove_all_match
        — the latter made every delete scan every job's files and blocked the
        worker.
        """
        for prefix in self._JOB_DIRS:
            shutil.rmtree(self.abs_path(os.path.join(prefix, job_id)), ignore_errors=True)

        for prefix, name in self._JOB_FILES:
            try:
                os.remove(self.abs_path(os.path.join(prefix, name.format(job_id=job_id))))
            except OSError:
                pass

        for prefix, pattern in self._JOB_GLOBS:
            for f in glob.glob(self.abs_path(os.path.join(prefix, pattern.format(job_id=job_id)))):
                try:
                    os.remove(f)
                except OSError:
                    pass

    def remove_all_match(self, key):
        # NOTE: walks the ENTIRE storage tree; prefer remove_job(job_id) for a
        # single job. Kept for callers that match on an arbitrary key.
        files_to_delete = []
        dirs_to_delete = []
        for root, dirs, files in os.walk(str(self.path)):
            files_to_delete += [os.path.join(root, f) for f in files if key in f]
            dirs_to_delete += [os.path.join(root, d) for d in dirs if key in d]

        for f in files_to_delete:
            try:
                os.remove(f)
            except:
                pass

        for d in dirs_to_delete:
            try:
                shutil.rmtree(d)
            except:
                pass
