"""The response class of the api.

Every route answers json -- the only html is the root page -- but only the 413
handler ever named that type: the rest took Flask's ``text/html`` default. The
webapp parses by the type it asks for and never minded, a browser opening an
url of the api is handed html, and ``X-Content-Type-Options: nosniff`` then
keeps it from rendering what it was given. Importing ``Response`` from here
instead of from flask makes the type right at every call site, unchanged.
"""

from flask import Response as FlaskResponse


class Response(FlaskResponse):
    """@brief A Flask response whose type defaults to ``application/json``.

    A route that answers something else -- a file, the html root -- passes its
    own ``mimetype`` as before and is unaffected.
    """

    default_mimetype = "application/json"
