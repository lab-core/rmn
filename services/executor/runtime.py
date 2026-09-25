"""What the executor needs wherever it works.

The clients are passed to the tasks explicitly; these are the pieces that
have no state of their own -- the timestamped print, the heartbeat that keeps
a long job from looking idle, the batch sizes, and the template boxes.
"""

import datetime as dt
import threading
import os
from python.process_copy.config import (
    DEFAULT_GRADE_BOX,
    DEFAULT_MATRICULE_BOX,
)
from python.process_copy.parser import grade_box, matricule_box


MAX_RETRY = int(os.getenv("MAX_RETRY", "5"))


MAX_IDLE_TIME = 120


BATCH_SIZE = 500


# override print
old_print = print


def timestamped_print(*args, **kwargs):
  old_print(dt.datetime.now(), *args, **kwargs)


print = timestamped_print


class Heartbeat:
    """Refresh a job's ``alive_time`` from a background thread while it is being
    processed.

    Grading and finalization can run far longer than ``MAX_IDLE_TIME`` without
    otherwise touching ``alive_time``; without a heartbeat the idle checker
    treats the job as dead and requeues it, so a second executor processes it
    concurrently and ``retry`` climbs until a healthy job is flipped to ERROR.
    If the executor really dies, the thread dies with it and the job is
    correctly requeued.
    """

    def __init__(self, db, job_id, interval=MAX_IDLE_TIME // 3):
        self._db = db
        self._job_id = job_id
        self._interval = max(5, interval)
        self._stop = threading.Event()
        self._thread = None

    def _touch(self):
        try:
            self._db.eval_jobs_collection().update_one(
                {"job_id": self._job_id},
                {"$set": {"alive_time": dt.datetime.now(dt.UTC)}},
            )
        except Exception as e:
            print("Heartbeat failed:", e)

    def _beat(self):
        while not self._stop.wait(self._interval):
            self._touch()

    def __enter__(self):
        # beat once before the job is touched: the thread only writes after a
        # full interval, and a job set to FINALIZING with the alive_time of an
        # old run was requeued by the idle sweep of any executor starting in
        # the meantime, then finalized by several executors at once (job
        # a119c7b2: four runs, one overwrote the zips with 17 of 59 copies)
        self._touch()
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        return False


def apply_template_boxes(box_grade_list, box_matricule_list, regular_box_matricule_list):
    """Point the recogniser at the boxes of this job's templates.

    The boxes are module globals of ``config``; a job whose template defines
    no box used to keep the previous job's coordinates (one process handles
    many jobs outside production), so it now falls back to the defaults.
    """
    def rounded(values, default):
        return tuple(round(x, 2) for x in values) if values is not None else default

    matricule_box['exam']['regular'] = rounded(regular_box_matricule_list, DEFAULT_MATRICULE_BOX['exam']['regular'])
    matricule_box['exam']['front'] = rounded(box_matricule_list, DEFAULT_MATRICULE_BOX['exam']['front'])
    grade_box['exam']['grade'] = rounded(box_grade_list, DEFAULT_GRADE_BOX['exam']['grade'])
