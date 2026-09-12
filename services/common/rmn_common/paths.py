"""File-name safety for values that come from an uploaded csv."""

from pathlib import Path


def safe_path_component(value, default="_"):
    """One file or folder name built from a csv cell (a name, a group).

    Keeps spaces and accents: Moodle re-imports the feedback zip by the
    participant id in the folder name, the rest is cosmetic. Removes what
    would leave the job folder: path separators, NUL, and the "." / ".."
    names.
    """
    text = str(value).replace("/", "_").replace("\\", "_").replace("\x00", "").strip()
    if text in ("", ".", ".."):
        return default
    return text


def ensure_within(path, root):
    """Resolve ``path`` and raise ValueError if it is not under ``root``."""
    resolved, root = Path(path).resolve(), Path(root).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"{resolved} is outside {root}")
    return resolved
