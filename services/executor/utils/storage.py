"""The shared storage, rooted at the project when STORAGE is not set."""

import os
from pathlib import Path

from rmn_common.storage import (
    Storage as _Storage,
    create_tree,
    move,
)  # noqa: F401  (re-exported)

# either service root or project root depending on the environment
ROOT_DIR = Path(__file__).resolve().parent.parent
if os.getenv("ENVIRONMENT") != "production":
    ROOT_DIR = ROOT_DIR.parent.parent


class Storage(_Storage):
    default_path = ROOT_DIR.joinpath("storage")

    def clean_storage(self, job_id):
        """Remove the per-job folders the recognition produced (missing ones are fine)."""
        for prefix in ("documents", "cover_pages", "incorrect_files"):
            self.remove_tree(os.path.join(prefix, job_id))
