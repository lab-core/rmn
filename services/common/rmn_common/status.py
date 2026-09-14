"""Statuses stored in MongoDB and compared by the webapp.

The values are the strings on the wire: the webapp compares against them
literally, so they are not free to change: the webapp's copy is generated from
this module by :mod:`rmn_common.typescript` (``generated/rmn-contracts.ts``).
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
    # like the other two-word statuses. Was "NOT_READY" until v1.5 (the server's
    # copy said "NOT READY" and matched nothing): documents of jobs in progress
    # at the upgrade need
    #   db.job_documents.updateMany({status: "NOT_READY"}, {$set: {status: "NOT READY"}})
    NOT_READY = "NOT READY"
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
