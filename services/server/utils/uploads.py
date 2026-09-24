"""What an upload is allowed to be, and where it lands while it is read."""

import os
import uuid
from zipfile import ZipFile
import pandas as pd
from werkzeug.utils import secure_filename
from context import TEMP_FOLDER, storage


def temp_upload_path(filename):
    """A path under TEMP_FOLDER that no other request can be using.

    The client filename alone collided: two users uploading ``notes.csv`` in
    the same second overwrote each other's temp file, so one job got the
    other's roster.
    """
    os.makedirs(TEMP_FOLDER, exist_ok=True)
    return TEMP_FOLDER.joinpath(f"{uuid.uuid4()}_{secure_filename(filename or '') or 'upload'}")


def save_csv(file_name, notes_file_id):
    # Check if separated by ; or , -> and transform to real csv (,) if needed
    df_comma = pd.read_csv(file_name, nrows=1, sep=",")
    df_semi = pd.read_csv(file_name, nrows=1, sep=";")
    if df_semi.shape[1] > df_comma.shape[1]:
        df_semi = pd.read_csv(file_name, sep=";")
        df_semi.to_csv(file_name)  # save with a ',' separator
    return storage.move_to(file_name, notes_file_id)


FRONT_PAGE_MAX_MEMBERS = 5000


FRONT_PAGE_MAX_UNZIPPED_BYTES = 4 * 1024 ** 3


def extract_bounded(zip_path, dest, max_members=None, max_bytes=None):
    """Extract ``zip_path`` into ``dest``; the error message when it exceeds the budget.

    The declared sizes are summed before anything is written. Member names
    are made safe by ``ZipFile.extract`` itself (``..`` and absolute paths are
    stripped). The limits default to the module constants at call time.
    """
    max_members = FRONT_PAGE_MAX_MEMBERS if max_members is None else max_members
    max_bytes = FRONT_PAGE_MAX_UNZIPPED_BYTES if max_bytes is None else max_bytes
    with ZipFile(zip_path, "r") as zip_ref:
        members = zip_ref.infolist()
        if len(members) > max_members:
            return f"Error: the zip has {len(members)} members (max {max_members})."
        total = sum(m.file_size for m in members)
        if total > max_bytes:
            return f"Error: the zip inflates to {total} bytes (max {max_bytes})."
        zip_ref.extractall(dest)
    return None
