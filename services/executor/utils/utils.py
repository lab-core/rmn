from enum import Enum


class Job_Status(Enum):
    QUEUED = "QUEUED"
    RUN = "RUN"
    CORRECTED = "CORRECTED"
    VALIDATION = "VALIDATION"
    FINALIZING = "FINALIZING"
    ARCHIVED = "ARCHIVED"
    ERROR = "ERROR"


class Document_Status(Enum):
    VALIDATED = "VALIDATED"
    TO_VALIDATE = "TO VALIDATE"
    HIGH_ACCURACY = "HIGH ACCURACY"
    NOT_READY = "NOT_READY"
    READY = "READY"
