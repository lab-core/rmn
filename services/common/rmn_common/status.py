"""Statuses stored in MongoDB and compared by the webapp.

The values are the strings on the wire: the webapp compares against them
literally (``'TO VALIDATE'``, ``'NOT_READY'``, ``'Administrateur'``), so they
are not free to change.
"""

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
    # written by the executor and matched by the webapp; the server's former
    # copy said "NOT READY" (with a space) and matched nothing
    NOT_READY = "NOT_READY"
    READY = "READY"
    DELETED = "DELETED"


class Output_File(Enum):
    PREVIEW_FILE = "preview_file"
    NOTES_CSV_FILE = "notes_csv_file"
    ZIP_FILE = "zip_file"
    STATS_PDF_FILE = "stats_pdf_file"


class User_Role(Enum):
    USER = "Utilisateur"
    ADMIN = "Administrateur"
