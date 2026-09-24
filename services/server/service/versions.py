"""Every version of a copy that was ever uploaded, and the latest of them."""

import glob
import os
import shutil
from context import mongo, storage


def version_basename(filename):
    version_dir = os.path.join(os.path.dirname(filename), "versions")
    version_name = os.path.basename(filename).rsplit(".", 1)[0]
    return os.path.join(version_dir, version_name)


def save_new_pdf_version(filename):
    version_base = version_basename(filename)
    # the split step makes this directory, but a copy that arrives without one
    # used to fail inside the upload thread, after the 200 had been sent: the
    # teacher saw a successful upload and the file was gone
    os.makedirs(os.path.dirname(version_base), exist_ok=True)
    all_versions = glob.glob(version_base+"-*.pdf")
    n_version = len(all_versions)

    # create backup of the file
    version_filepath = version_base + "-%d.pdf" % n_version
    print(f"Save new pdf version ({n_version}):", version_filepath)
    shutil.copy(filename, version_filepath)
    return version_filepath


def get_last_version_document(rel_filepath):
    version_base = version_basename(rel_filepath)
    filename_base = storage.abs_path(version_base)
    # print("file_base", filename_base)
    all_versions = glob.glob(filename_base + "-*.pdf")
    return len(all_versions) - 1


def get_last_version(job_id, rel_filepath):
    db = mongo["RMN"]
    return db["versions"].count_documents({"job_id": job_id, "rel_filepath": rel_filepath}) - 1
