"""The wire values the webapp compares against."""

from rmn_common.status import Document_Status, Job_Status, User_Role


def test_status_values_match_what_is_stored():
    assert Job_Status.QUEUED.value == "QUEUED"
    assert Job_Status.FINALIZING.value == "FINALIZING"
    # the statuses whose value is not their name
    assert Document_Status.TO_VALIDATE.value == "TO VALIDATE"
    assert Document_Status.HIGH_ACCURACY.value == "HIGH ACCURACY"
    # the executor writes it and the webapp matches it with the underscore
    assert Document_Status.NOT_READY.value == "NOT READY"
    assert User_Role.ADMIN.value == "Administrateur"
