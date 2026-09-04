import re
from enum import Enum


class Job_Status(Enum):
    SPLIT = "SPLIT"
    RETRY = "RETRY"
    CORRECTED = "CORRECTED"
    IGNORED = "IGNORED"
    QUEUED = "QUEUED"
    RUN = "RUN"
    VALIDATION = "VALIDATION"
    VALIDATED = "VALIDATED"
    FINALIZING = "FINALIZING"
    ARCHIVED = "ARCHIVED"
    ERROR = "ERROR"


class Document_Status(Enum):
    VALIDATED = "VALIDATED"
    TO_VALIDATE = "TO VALIDATE"
    HIGH_ACCURACY = "HIGH ACCURACY"
    NOT_READY = "NOT_READY"
    READY = "READY"
    DELETED = "DELETED"


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
    """Iterate (key, value) pairs from either the dict or the [[key, value], ...]
    wire shape used for ``n_pages_per_question``."""
    if isinstance(n_pages_per_question, dict):
        return list(n_pages_per_question.items())
    return [(item[0], item[1]) for item in n_pages_per_question]


def active_question_keys(n_pages_per_question):
    """Numerically sorted keys of the questions that are not ignored.

    A question is ignored when it has 0 page (it then also has 0 point): the
    template box exists on the cover but the question is not part of the exam.
    """
    keys = [key for key, pages in _question_items(n_pages_per_question) if pages]
    return sorted(keys, key=question_sort_key)


def ignored_positions(n_pages_per_question):
    """0-based positions (index in ``job_documents.grades``) of ignored questions."""
    return {
        question_position(key)
        for key, pages in _question_items(n_pages_per_question)
        if not pages
    }
