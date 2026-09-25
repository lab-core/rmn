"""The bank of digits a human has confirmed, kept to retrain the recogniser.

Every number the recogniser reads is a handful of digit crops; when a human
later confirms what that number was, each crop gets a label that no synthetic
dataset can give us -- the digits real students write, scanned by the machines
of this faculty. This module stages the crops while a job is read and turns
the staged readings into labelled samples once the humans are done with the
job (``promote_job``).

Sizes
-----
A digit is stored as a **64 x 64** grayscale square, the thresholded mask the
classifier itself sees, centred with no margin.

The model eats 28 x 28 (``classifier``/``train``), but a bank stored at 28
would be a dead end: measured on the recognition fixtures, the crops
``extract_digit`` cuts at 300 dpi are 38-62 px for a handwritten matricule
digit and 58-72 px for a printed grade, so 28 x 28 is a 2.2x to 2.6x
downscale. Storing that would freeze both today's resolution and today's
framing -- ``config.digit_margins`` is a training-time choice, and the margin
cannot be widened again once the pixels outside it are gone.

64 keeps essentially every digit at its native size (the tallest grades shrink
by 1.13x), is a power of two, costs 4 KB raw and a few hundred bytes as a PNG,
and any input the model may want later -- 28, 32, 48, with any margin -- is a
pad-and-downscale away through the very ``make_square`` the recogniser uses
(:func:`view`). Upscaling, which is what a 28 x 28 bank would force, invents
detail instead.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Dict, Iterator, List, Optional

import cv2
import numpy as np

from process_copy.imaging import make_square, storage as default_storage

# Side of a stored digit, in pixels. See the module docstring: it is the
# native size of the crops, not the model's input.
SAMPLE_SIZE = 64

BANK_DIR = "digit_bank"
# staged crops live under the job so deleting the job drops them (see
# rmn_common.storage.Storage._JOB_DIRS); labelled samples never do.
STAGED_DIR = os.path.join(BANK_DIR, "staged")
SAMPLES_DIR = os.path.join(BANK_DIR, "samples")
INDEX_FILE = os.path.join(BANK_DIR, "index.jsonl")

# what a reading was read off, kept with every sample: the three paths reach
# the same classifier but not the same ink
MATRICULE = "matricule"
GRADE_BOX = "grade_box"
INK_GRADE = "ink_grade"


def enabled() -> bool:
    """Whether readings are staged at all (``DIGIT_BANK=0`` turns it off)."""
    return os.getenv("DIGIT_BANK", "1") not in ("0", "false", "False", "")


def canonical(roi: np.ndarray) -> np.ndarray:
    """The crop as it is stored: a ``SAMPLE_SIZE`` square, digit centred, no margin.

    Args:
        roi: The masked region ``extract_digit`` hands the classifier.

    Returns:
        A ``(SAMPLE_SIZE, SAMPLE_SIZE)`` uint8 image, the digit white on black.
    """
    return make_square(roi, size=SAMPLE_SIZE, margin=0)


def view(sample: np.ndarray, size: int = 28, margin: float = 0.1) -> np.ndarray:
    """A stored sample framed the way the model wants it.

    This is how a bank stored at 64 becomes training data for an input of any
    size: the same padding and resizing ``extract_digit`` applies at run time
    (``config.digit_margins``).

    Args:
        sample: A stored sample, as :func:`canonical` wrote it.
        size: Side of the wanted image, 28 for the current model.
        margin: Margin around the digit, as a fraction of its size.

    Returns:
        A ``(size, size)`` uint8 image.
    """
    return make_square(sample, size=size, margin=margin)


class Reading:
    """The ordered digit crops of one number, before anyone has confirmed it.

    A reading is kept only if the recogniser used it (:meth:`keep`): the ink
    pass reads candidates it then throws away, and labelling those with a
    confirmed grade would poison the bank.
    """

    def __init__(self, context: "Recording", meta: Dict[str, Any]):
        self.context = context
        self.meta = meta
        self.crops: List[np.ndarray] = []
        self.kept = False

    def add(self, roi: np.ndarray) -> None:
        """Record one digit crop, in reading order."""
        self.crops.append(canonical(roi))

    def keep(self, **meta: Any) -> None:
        """Mark the reading as the one the recogniser went with.

        Args:
            **meta: What the caller knows and the promotion needs: ``dot``
                (index of the decimal point among the digits), ``value``
                (what was read), ``question_index``, ``box_index``.
        """
        self.meta.update(meta)
        self.kept = True


class Recording:
    """Staging of the readings of one copy, while it is being read.

    A reading is written out when the recording closes, not when it ends: the
    ink pass reads every candidate mark and only knows afterwards which one it
    went with (``ink_grades.pick``). Only the kept readings and the one that
    just closed are held, so what a copy costs stays flat.
    """

    def __init__(
        self,
        storage: Any,
        job_id: str,
        document_index: Optional[int],
        kind: str,
        meta: Optional[Dict[str, Any]] = None,
    ):
        self.storage = storage
        self.job_id = job_id
        self.document_index = document_index
        self.kind = kind
        self.meta = dict(meta or {})
        self.reading: Optional[Reading] = None
        self.last: Optional[Reading] = None
        self.kept: List[Reading] = []

    def close(self, reading: Reading) -> None:
        """A reading has ended: keep it if it was already claimed, remember it."""
        self.reading = None
        self.last = reading
        if reading.kept and reading not in self.kept:
            self.kept.append(reading)

    def flush_all(self) -> int:
        """Write every kept reading; returns how many files were written."""
        written = 0
        for reading in self.kept:
            if self.flush(reading):
                written += 1
        self.kept = []
        return written

    def staged_dir(self) -> str:
        return self.storage.abs_path(
            os.path.join(STAGED_DIR, self.job_id, str(self.document_index))
        )

    def flush(self, reading: Reading) -> Optional[str]:
        """Write a kept reading to the staging area; returns the file written."""
        if not reading.kept or not reading.crops:
            return None
        meta = dict(
            self.meta,
            **reading.meta,
            kind=self.kind,
            job_id=self.job_id,
            document_index=self.document_index,
            n_digits=len(reading.crops),
            size=SAMPLE_SIZE,
            read_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        os.makedirs(self.staged_dir(), exist_ok=True)
        path = os.path.join(self.staged_dir(), f"{uuid.uuid4()}.npz")
        np.savez_compressed(
            path, crops=np.stack(reading.crops), meta=np.array(json.dumps(meta))
        )
        return path


# The recording in force in this process. The recogniser runs a copy per
# process (``batch.process_all``), each with its own module state, and the
# crops of a number are cut one after another inside one call, so a single
# current reading is enough -- and it keeps ``extract_digit``'s signature,
# which four call sites pass through, free of bank arguments.
_current: Optional[Recording] = None


@contextmanager
def recording(
    job_id: Optional[str],
    document_index: Optional[int],
    kind: str,
    storage: Any = None,
    **meta: Any,
) -> Iterator[Optional[Recording]]:
    """Stage the digit crops read inside this block, for one copy.

    Nothing is staged without a job id, or when ``DIGIT_BANK=0``: the
    development entry points read loose files that no human will confirm.

    Args:
        job_id: The job the copy belongs to.
        document_index: The copy, as ``job_documents`` numbers it.
        kind: :data:`MATRICULE`, :data:`GRADE_BOX` or :data:`INK_GRADE`.
        storage: The storage to stage into; the executor's by default.
        **meta: Kept with every reading of the copy (``question_index`` for
            the ink pass, which reads one question at a time).
    """
    global _current
    if not job_id or not enabled():
        yield None
        return
    previous = _current
    current = Recording(
        storage or default_storage, job_id, document_index, kind, meta)
    _current = current
    try:
        yield current
    finally:
        _current = previous
        try:
            current.flush_all()
        except Exception as e:  # a bank write must never fail a job
            print("Could not stage the digit readings of a copy:", e)


@contextmanager
def reading(**meta: Any) -> Iterator[Reading]:
    """One number inside a :func:`recording`; flushed if it is kept."""
    context = _current
    if context is None:
        yield Reading(None, meta)  # type: ignore[arg-type]
        return
    current = Reading(context, meta)
    context.reading = current
    try:
        yield current
    finally:
        context.close(current)


def annotate(**meta: Any) -> None:
    """Add to what is known about the reading that is open, without keeping it."""
    context = _current
    if context is not None and context.reading is not None:
        context.reading.meta.update(meta)


def keep(**meta: Any) -> None:
    """Keep the reading that is open: the recogniser went with this number."""
    context = _current
    if context is not None and context.reading is not None:
        context.reading.keep(**meta)


def keep_last(**meta: Any) -> None:
    """Keep the reading that just closed.

    For a caller that reads several numbers before it knows which one it
    wants -- ``ink_grades.pick`` ranks the marks of a page and returns the
    first that holds up.
    """
    context = _current
    if context is None or context.last is None:
        return
    context.last.keep(**meta)
    if context.last not in context.kept:
        context.kept.append(context.last)


def record(roi: np.ndarray) -> None:
    """Add a crop to the open reading, if any. Called by ``extract_digit``."""
    context = _current
    if context is None or context.reading is None:
        return
    try:
        context.reading.add(roi)
    except Exception as e:  # the recognition matters, the bank does not
        print("Could not record a digit crop:", e)


def digits_of(value: float, n_digits: int, dot: Optional[int]) -> Optional[str]:
    """The digit string a confirmed number would be written with, or None.

    The crops are what the student wrote; a confirmed value can only label
    them when it is written with exactly as many digits, in the same places.
    ``2.5`` read as three crops (``dot`` = 2, so two whole digits) is not a
    number anyone wrote as ``ab.c``, and is dropped rather than guessed.

    Args:
        value: The number a human confirmed.
        n_digits: How many crops the reading holds.
        dot: Index of the decimal point among the digits, ``None`` when the
            number has no decimal part (a matricule).

    Returns:
        ``n_digits`` characters, or ``None`` when the value cannot be written
        that way.
    """
    if value is None or n_digits <= 0:
        return None
    decimals = 0 if dot is None else n_digits - int(dot)
    if decimals < 0:
        return None
    whole = n_digits - decimals
    text = f"{float(value):.{decimals}f}"
    integer, _, fraction = text.partition(".")
    if integer.startswith("-"):
        return None
    # the student writes no leading zero, so the whole part has to fit exactly
    if len(integer) != whole or len(fraction) != decimals:
        return None
    digits = integer + fraction
    if not digits.isdigit() or len(digits) != n_digits:
        return None
    # the rounding of the format above must not have changed the value
    if abs(float(text) - float(value)) > 1e-9:
        return None
    return digits


def _label_dir(storage: Any, label: str) -> str:
    return storage.abs_path(os.path.join(SAMPLES_DIR, label))


def add_sample(storage: Any, crop: np.ndarray, label: str, meta: Dict[str, Any]) -> bool:
    """Write one labelled digit into the bank, unless it is already there.

    The file name is the hash of the pixels, so re-promoting a job, or the
    same copy read twice, adds nothing.

    Returns:
        True when the sample was new.
    """
    ok, png = cv2.imencode(".png", crop)
    if not ok:
        return False
    digest = sha1(png.tobytes()).hexdigest()
    directory = _label_dir(storage, label)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{digest}.png")
    if os.path.exists(path):
        return False
    with open(path, "wb") as f:
        f.write(png.tobytes())
    index = storage.abs_path(INDEX_FILE)
    os.makedirs(os.path.dirname(index), exist_ok=True)
    with open(index, "a") as f:
        f.write(json.dumps(dict(meta, sha1=digest, label=int(label), size=SAMPLE_SIZE)) + "\n")
    return True


def _confirmed_matricule(job: Dict[str, Any], doc: Optional[Dict[str, Any]]) -> Optional[str]:
    """The matricule of a copy when a human validated it, else None.

    A job created without ``validate_matricule`` marks its copies VALIDATED by
    itself (``batch.process_all``), so the status alone proves nothing.
    """
    if not doc or not job.get("validate_matricule", True):
        return None
    if doc.get("status") != "VALIDATED":
        return None
    matricule = str(doc.get("matricule") or "")
    return matricule if matricule.isdigit() else None


def _confirmed_grade(
    meta: Dict[str, Any], doc: Optional[Dict[str, Any]], questions: Dict[int, Any]
) -> Optional[float]:
    """The grade a human confirmed for a staged reading, else None.

    ``job_questions.grade`` and ``job_documents.grades`` are only ever written
    by a human (see ``rmn_common.auto_grade``: a read value is a suggestion
    until it is confirmed in the correction screen), which is exactly the
    ground truth this bank needs.
    """
    question_index = meta.get("question_index")
    if question_index is not None:
        return questions.get(int(question_index))
    box_index = meta.get("box_index")
    if box_index is None or not doc:
        return None
    grades = [g for g in (doc.get("grades") or [])]
    if not grades:
        return None
    # the table is Q1..Qn then the total, which is their sum
    if int(box_index) == len(grades):
        return sum(g for g in grades if g is not None)
    if 0 <= int(box_index) < len(grades):
        return grades[int(box_index)]
    return None


def saves_images(db: Any, user_id: Optional[str]) -> bool:
    """Whether this teacher lets the images of their copies be kept.

    ``saveVerifiedImages`` is the switch in the user profile, and it is what
    the bank asks: staged crops die with the job, a banked sample outlives it,
    so the consent is about the promotion and not about the reading.

    It is on by default, here and where a user is created, so a teacher who
    never opened the profile screen contributes; a row that predates the flag,
    and a deleted user, keep that default (as ``finalize`` does for
    ``moodleStructureInd``). Turning the switch off stores a real ``false``
    and is honoured.
    """
    user = db.users_collection().find_one({"username": user_id}) or {}
    return bool(user.get("saveVerifiedImages", True))


def promote_job(db: Any, job_id: str, storage: Any = None, remove: bool = True) -> Dict[str, int]:
    """Turn the staged readings of a job into labelled samples.

    Only what a human settled is used: a matricule the job asked to be
    validated and that reached VALIDATED, and grades confirmed in the
    correction screen. A reading whose crops cannot be matched one for one
    with the confirmed number is dropped (see :func:`digits_of`). Nothing is
    kept at all unless the teacher who owns the job turned
    ``saveVerifiedImages`` on (:func:`saves_images`).

    Args:
        db: The executor's ``Database``.
        job_id: The job whose staged readings are promoted.
        storage: The storage holding the bank; the executor's by default.
        remove: Delete the staged readings once they are promoted.

    Returns:
        Counts: ``readings``, ``promoted``, ``samples``, ``skipped``, and
        ``refused`` when the owner has not opted in.
    """
    storage = storage or default_storage
    counts = {"readings": 0, "promoted": 0, "samples": 0, "skipped": 0}
    staged_root = storage.abs_path(os.path.join(STAGED_DIR, job_id))
    if not os.path.isdir(staged_root):
        return counts

    job = db.eval_jobs_collection().find_one({"job_id": job_id}) or {}
    if not saves_images(db, job.get("user_id")):
        # the crops stay staged and go with the job; nothing reaches the bank
        counts["refused"] = 1
        return counts
    documents = {
        d["document_index"]: d
        for d in db.documents_collection().find({"job_id": job_id})
    }
    questions: Dict[int, Dict[int, Any]] = {}
    for q in db.questions_collection().find({"job_id": job_id}):
        if q.get("grade") is not None:
            questions.setdefault(q["document_index"], {})[
                int(q["question_index"])
            ] = q["grade"]

    for root, _dirs, files in os.walk(staged_root):
        for name in sorted(files):
            if not name.endswith(".npz"):
                continue
            path = os.path.join(root, name)
            counts["readings"] += 1
            try:
                with np.load(path, allow_pickle=False) as data:
                    crops = data["crops"]
                    meta = json.loads(str(data["meta"]))
            except Exception as e:
                print("Unreadable staged reading", path, ":", e)
                counts["skipped"] += 1
                continue

            doc = documents.get(meta.get("document_index"))
            if meta.get("kind") == MATRICULE:
                confirmed = _confirmed_matricule(job, doc)
                labels = confirmed if confirmed and len(confirmed) == len(crops) else None
            else:
                grade = _confirmed_grade(
                    meta, doc, questions.get(meta.get("document_index"), {})
                )
                labels = digits_of(grade, len(crops), meta.get("dot"))

            if not labels:
                counts["skipped"] += 1
                continue
            for position, (crop, label) in enumerate(zip(crops, labels)):
                if add_sample(
                    storage,
                    crop,
                    label,
                    dict(meta, position=position, read=_read_digit(meta, position)),
                ):
                    counts["samples"] += 1
            counts["promoted"] += 1
            if remove:
                os.remove(path)
    return counts


def _read_digit(meta: Dict[str, Any], position: int) -> Optional[int]:
    """What the model had read at ``position``, when the reading recorded it.

    Kept with the sample so a training run can weigh, or simply count, the
    digits the model gets wrong today.
    """
    read = meta.get("read")
    if isinstance(read, str) and position < len(read) and read[position].isdigit():
        return int(read[position])
    return None


def samples(storage: Any = None, size: int = SAMPLE_SIZE, margin: float = 0.0):
    """The whole bank as ``(x, y)`` arrays, framed for an input of ``size``.

    ``train.create_dataset`` writes exactly this pair; with ``size=28`` and a
    margin of ``config.digit_margins`` the bank is a drop-in addition to the
    training set.

    Returns:
        ``x`` of shape ``(n, size, size)`` uint8 and ``y`` of shape ``(n,)``.
    """
    storage = storage or default_storage
    x: List[np.ndarray] = []
    y: List[int] = []
    root = storage.abs_path(SAMPLES_DIR)
    if not os.path.isdir(root):
        return np.empty((0, size, size), dtype="uint8"), np.array([], dtype="int")
    for label in sorted(os.listdir(root)):
        if not label.isdigit():
            continue
        for name in sorted(os.listdir(os.path.join(root, label))):
            if not name.endswith(".png"):
                continue
            img = cv2.imread(os.path.join(root, label, name), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            x.append(img if size == img.shape[0] and not margin else view(img, size, margin))
            y.append(int(label))
    if not x:
        return np.empty((0, size, size), dtype="uint8"), np.array([], dtype="int")
    return np.stack(x), np.array(y, dtype="int")


def counts(storage: Any = None) -> Dict[int, int]:
    """How many samples the bank holds per digit."""
    storage = storage or default_storage
    root = storage.abs_path(SAMPLES_DIR)
    if not os.path.isdir(root):
        return {}
    return {
        int(label): len([f for f in os.listdir(os.path.join(root, label)) if f.endswith(".png")])
        for label in sorted(os.listdir(root))
        if label.isdigit()
    }
