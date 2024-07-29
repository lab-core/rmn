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

class User_Role(Enum):
    USER = "Utilisateur"
    ADMIN = "Administrateur"
