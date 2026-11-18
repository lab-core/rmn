"""The trace of who gave a copy its matricule, and when.

A copy's ``matricule`` and ``status`` only hold the last answer: when a copy
ends up with the wrong student, nothing tells whether the reader proposed
them or a person picked them, nor when. Every change is therefore appended to
the copy's ``matricule_history``: the reader's proposal, then each correction
or status change made on the matricule page, by the owner or by a share link.
"""

import datetime as dt
from typing import Any

FIELD = "matricule_history"

# a copy is corrected a handful of times; a page clicked through again and
# again must not grow the document without end
MAX_ENTRIES = 50


def history_entry(by: str, **values: Any) -> dict[str, Any]:
    """One change of a copy, dated now.

    Args:
        by: Who made it: ``reader``, ``owner`` or ``share:<scope>``.
        **values: What changed, the values left None omitted (``matricule``,
            ``status``, ``previous_matricule``, ``previous_status``,
            ``confidence``).

    Returns:
        The entry to push on the copy's history.
    """
    entry = {"date": dt.datetime.now(dt.UTC), "by": by}
    entry.update({k: v for k, v in values.items() if v is not None})
    return entry


def push_history(entry: dict[str, Any]) -> dict[str, Any]:
    """The update operator that appends ``entry`` to a copy's history.

    Args:
        entry: An entry made by ``history_entry``.

    Returns:
        A ``$push`` to merge in a ``job_documents`` update, which keeps the
        last ``MAX_ENTRIES`` entries.
    """
    return {FIELD: {"$each": [entry], "$slice": -MAX_ENTRIES}}
