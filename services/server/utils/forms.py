"""Reading the fields of a request form."""

import json
from flask import Response, abort


def form_int(request_form, field, default=None):
    """The integer in ``request_form[field]``, or ``default`` when it is absent.

    A value that is not an integer ends the request with a 400 in the shape
    the routes use for a missing field. A bare ``int()`` raised a ValueError,
    so a malformed ``document_index`` or ``version`` was a 500.

    Args:
        request_form: The form (or query args) of the request.
        field: The name of the field to read.
        default: What to return when the field is absent.

    Returns:
        The value of the field as an int, or ``default``.
    """
    value = request_form.get(field)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        abort(
            Response(
                response=json.dumps({"response": f"Error: {field} is not a number."}),
                status=400,
            )
        )
