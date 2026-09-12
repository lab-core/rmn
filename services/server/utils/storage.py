"""The shared storage, rooted next to the server when STORAGE is not set."""

from pathlib import Path

from rmn_common.storage import (
    Storage as _Storage,
    create_tree,
    move,
)  # noqa: F401  (re-exported)

ROOT_DIR = Path(__file__).resolve().parent.parent


class Storage(_Storage):
    default_path = ROOT_DIR.joinpath("storage")
