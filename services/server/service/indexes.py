"""The indexes the server makes sure exist, every time it starts.

Mongo creates a collection on its first write, so these cannot be a one-off
migration: a fresh database would have nothing to index. ``create_index`` is
idempotent and costs nothing once the index is there, so the server ensures
them at start-up the way it already ensures the token indexes.
"""


def ensure_job_question_indexes(database):
    """Index the shapes every ``job_questions`` query uses.

    The collection is read by job alone (the correction screen lists a job's
    copies), by ``(job_id, document_index)`` for one copy, and by
    ``(job_id, question_index)`` for a question's reading pass. None of them
    had an index: a job of 6041 documents showed up in Mongo's slow query log
    as a 141 ms COLLSCAN for a single ``find``, and the collection only grows.

    Both indexes start with ``job_id``, so a query on the job alone is served
    by either prefix.

    Args:
        database: The ``RMN`` database.
    """
    collection = database["job_questions"]
    collection.create_index([("job_id", 1), ("document_index", 1)], name="job_document")
    collection.create_index([("job_id", 1), ("question_index", 1)], name="job_question")
