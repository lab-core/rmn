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


class Output_File(Enum):
    PREVIEW_FILE = "preview_file"
    NOTES_CSV_FILE = "notes_csv_file"
    ZIP_FILE = "zip_file"
    STATS_PDF_FILE = "stats_pdf_file"


class Client_Type(Enum):
    JOB_EXECUTOR = "job_executor"
    WEB_CLIENT = "web_client"


class Document_Status(Enum):
    VALIDATED = "VALIDATED"
    TO_VALIDATE = "TO VALIDATE"
    HIGH_ACCURACY = "HIGH ACCURACY"
    NOT_READY = "NOT READY"
    DELETED = "DELETED"


class User_Role(Enum):
    USER = "Utilisateur"
    ADMIN = "Administrateur"


def validate_questions(
    n_pages_per_question, n_max_points_per_question, bonus_enabled_map
):
    """Check the per-question lists sent when a task is created.

    Each list is ``[["Q1", value], ...]`` (JS ``Array.from(map.entries())``).
    A question with 0 page is ignored (not part of the exam although its box
    exists on the template): it must then also have 0 point. Returns an error
    message (French, shown to the user) or ``None`` when the lists are valid.
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
