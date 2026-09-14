"""The ``Q<n>`` question keys shared by the task definition and the storage tree.

A task carries three per-question lists, ``[["Q1", value], ...]`` (JavaScript
``Array.from(map.entries())``), for pages, points and bonus. The keys name
folders and files on the executor side, and a question with 0 page is
*ignored*: its box exists on the cover template but it is not part of the exam.
"""

import re

QUESTION_KEY = re.compile(r"Q[1-9][0-9]*")


def validate_questions(
    n_pages_per_question, n_max_points_per_question, bonus_enabled_map
):
    """Check the per-question lists sent when a task is created.

    Returns an error message (French, shown to the user) or ``None`` when the
    lists are valid.
    """
    lists = (n_pages_per_question, n_max_points_per_question, bonus_enabled_map)
    for entries in lists:
        if not isinstance(entries, list) or any(
            not isinstance(e, (list, tuple)) or len(e) != 2 for e in entries
        ):
            return "format des questions invalide."
    keys = [e[0] for e in n_pages_per_question]
    if len(set(keys)) != len(keys):
        return "question en double."
    # the keys name folders and files on the executor side: only "Q<n>" is allowed
    if any(not isinstance(k, str) or QUESTION_KEY.fullmatch(k) is None for k in keys):
        return "les questions doivent être nommées Q1, Q2, ..."
    if any(not isinstance(e[1], bool) for e in bonus_enabled_map):
        return "le bonus d'une question doit être vrai ou faux."
    for entries in lists[1:]:
        if sorted(e[0] for e in entries) != sorted(keys):
            return "les questions des pages, des points et des bonus diffèrent."
    points = dict(n_max_points_per_question)
    for key, pages in n_pages_per_question:
        max_points = points[key]
        if isinstance(pages, bool) or not isinstance(pages, int) or pages < 0:
            return f"{key} : le nombre de pages doit être un entier positif ou nul."
        if (
            isinstance(max_points, bool)
            or not isinstance(max_points, (int, float))
            or max_points < 0
        ):
            return f"{key} : le nombre de points doit être positif ou nul."
        if pages == 0 and max_points != 0:
            return f"{key} : une question ignorée (0 page) doit valoir 0 point."
        if pages > 0 and max_points == 0:
            return f"{key} : une question corrigée doit valoir au moins un point."
    return None


def question_sort_key(item):
    """Numeric sort key for a "Q<n>" key or a ("Q<n>", value) pair.

    A plain sort of the keys is lexicographic ("Q10" < "Q2"), which mismaps
    per-question data once a task has 10 or more questions.
    """
    key = item[0] if isinstance(item, (list, tuple)) else item
    digits = re.sub(r"\D", "", str(key))
    return int(digits) if digits else 0


def question_position(key):
    """0-based position of a "Q<n>" key: "Q3" -> 2."""
    return question_sort_key(key) - 1


def _question_items(n_pages_per_question):
    """(key, value) pairs from either the dict or the [[key, value], ...] wire shape."""
    if isinstance(n_pages_per_question, dict):
        return list(n_pages_per_question.items())
    return [(item[0], item[1]) for item in n_pages_per_question]


def active_question_keys(n_pages_per_question):
    """Numerically sorted keys of the questions that are not ignored."""
    keys = [key for key, pages in _question_items(n_pages_per_question) if pages]
    return sorted(keys, key=question_sort_key)


def ignored_positions(n_pages_per_question):
    """0-based positions (index in ``job_documents.grades``) of ignored questions."""
    return {
        question_position(key)
        for key, pages in _question_items(n_pages_per_question)
        if not pages
    }
