"""How well a digit model reads the digit bank, and which part of it may train one.

The bank (:mod:`process_copy.digit_bank`) is split once and for all into a
training part and a test part, by copy: the seven digits of a matricule, or
every grade of one copy, are in the same part, so a model is never scored on
the handwriting it was trained on. The split depends on the copy only, not on
the bank's size, so a copy stays on its side as the bank grows and the scores
of two runs on the same bank compare.

A model is scored the way the recogniser uses it (``digits.extract_digit``):
each digit framed with every margin of ``config.digit_margins``, the
probabilities averaged. This module needs the LiteRT classifier only, not
TensorFlow, so the executor's tests run it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from hashlib import sha1
from typing import Any, Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np

from process_copy import digit_bank
from process_copy.config import digit_margins
from process_copy.imaging import storage as default_storage

# one copy in TEST_SHARE goes to the test part
TEST_SHARE = 5
# images per call to the classifier: bounds the memory of a large bank
BATCH = 512


@dataclass
class Bank:
    """The bank's samples with what the index knows of each.

    ``x`` holds the samples as stored (64 x 64), ``y`` their labels and
    ``meta`` the index line of each (``kind``, ``job_id``,
    ``document_index``, ``read`` ...), an empty dict when the index lacks it.
    """

    x: np.ndarray
    y: np.ndarray
    meta: List[Dict[str, Any]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.y)

    def subset(self, mask: np.ndarray) -> "Bank":
        """The samples where ``mask`` is True."""
        return Bank(
            self.x[mask], self.y[mask], [m for m, k in zip(self.meta, mask) if k]
        )

    def split(self) -> Tuple["Bank", "Bank"]:
        """The training part and the test part (see the module docstring)."""
        test = np.array([is_test(m) for m in self.meta], dtype=bool)
        return self.subset(~test), self.subset(test)


def is_test(meta: Dict[str, Any]) -> bool:
    """Whether a sample belongs to the test part: decided by its copy.

    Args:
        meta: The sample's index line. One with no copy recorded is placed by
            its own pixels (``sha1``).
    """
    if meta.get("job_id") is not None:
        key = f"{meta['job_id']}/{meta.get('document_index')}"
    else:
        key = str(meta.get("sha1", ""))
    return int(sha1(key.encode()).hexdigest()[:8], 16) % TEST_SHARE == 0


def read_index(storage: Any = None) -> Dict[str, Dict[str, Any]]:
    """The bank's index, by sample (the ``sha1`` its file is named after)."""
    storage = storage or default_storage
    index: Dict[str, Dict[str, Any]] = {}
    try:
        with open(storage.abs_path(digit_bank.INDEX_FILE)) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and "sha1" in entry:
                    index[entry["sha1"]] = entry
    except FileNotFoundError:
        pass
    return index


def load_bank(storage: Any = None) -> Bank:
    """Every sample of the bank, with its index line.

    The label is the directory a sample is in, as for
    :func:`digit_bank.samples`: the files are the bank, the index describes
    them.
    """
    storage = storage or default_storage
    index = read_index(storage)
    x: List[np.ndarray] = []
    y: List[int] = []
    meta: List[Dict[str, Any]] = []
    root = storage.abs_path(digit_bank.SAMPLES_DIR)
    labels = sorted(os.listdir(root)) if os.path.isdir(root) else []
    for label in labels:
        if not label.isdigit():
            continue
        for name in sorted(os.listdir(os.path.join(root, label))):
            if not name.endswith(".png"):
                continue
            img = cv2.imread(os.path.join(root, label, name), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            x.append(img)
            y.append(int(label))
            digest = name[: -len(".png")]
            meta.append(dict(index.get(digest, {}), sha1=digest))
    size = digit_bank.SAMPLE_SIZE
    if not x:
        return Bank(np.empty((0, size, size), dtype="uint8"), np.array([], dtype="int"))
    return Bank(np.stack(x), np.array(y, dtype="int"), meta)


def framed(samples: np.ndarray, margins: Iterable[float] = digit_margins) -> np.ndarray:
    """The samples framed for the model, every margin of each one in a row.

    Returns:
        ``(n * len(margins), 28, 28)`` uint8, sample by sample.
    """
    margins = list(margins)
    out = np.empty((len(samples) * len(margins), 28, 28), dtype="uint8")
    for i, sample in enumerate(samples):
        for j, margin in enumerate(margins):
            out[i * len(margins) + j] = digit_bank.view(sample, 28, margin)
    return out


def predict(
    classifier: Any, samples: np.ndarray, margins: Optional[List[float]] = None
) -> np.ndarray:
    """The digit the classifier reads in each 64 x 64 sample, as the recogniser does.

    Args:
        classifier: Anything with ``predict(batch)`` like ``DigitClassifier``.
        samples: ``(n, 64, 64)`` stored samples.
        margins: The framings averaged, ``config.digit_margins`` by default.

    Returns:
        ``(n,)`` digits.
    """
    margins = list(digit_margins if margins is None else margins)
    if not len(samples):
        return np.array([], dtype="int")
    probabilities = predict_images(classifier, framed(samples, margins))
    return (
        probabilities.reshape(len(samples), len(margins), -1)
        .mean(axis=1)
        .argmax(axis=1)
    )


def predict_images(classifier: Any, images: np.ndarray) -> np.ndarray:
    """Class probabilities for ``(n, 28, 28)`` uint8 images, in batches."""
    out = []
    for chunk in np.array_split(images, range(BATCH, len(images), BATCH)):
        batch = chunk.reshape(-1, 28, 28, 1).astype("float32") / 255
        out.append(classifier.predict(batch, verbose=0))
    return np.concatenate(out) if out else np.empty((0, 10), dtype="float32")


def scores(
    y: np.ndarray, predicted: np.ndarray, kinds: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Accuracy overall, per digit and per kind of number, and the confusions.

    Args:
        y: The true digits.
        predicted: What the model read.
        kinds: The kind of number of each sample (``digit_bank.MATRICULE`` ...).

    Returns:
        ``{"n", "correct", "accuracy", "per_digit": [{"n", "correct"}] * 10,
        "per_kind": {kind: {"n", "correct"}}, "confusion": 10 x 10}`` where
        ``confusion[true][read]`` counts the samples; ``accuracy`` is None on
        an empty set.
    """
    y = np.asarray(y, dtype="int")
    predicted = np.asarray(predicted, dtype="int")
    confusion = np.zeros((10, 10), dtype="int")
    np.add.at(confusion, (y, predicted), 1)
    right = y == predicted
    per_kind: Dict[str, Dict[str, int]] = {}
    for kind, ok in zip(kinds or [], right):
        entry = per_kind.setdefault(kind or "unknown", {"n": 0, "correct": 0})
        entry["n"] += 1
        entry["correct"] += int(ok)
    return {
        "n": int(len(y)),
        "correct": int(right.sum()),
        "accuracy": float(right.mean()) if len(y) else None,
        "per_digit": [
            {"n": int(confusion[d].sum()), "correct": int(confusion[d, d])}
            for d in range(10)
        ],
        "per_kind": per_kind,
        "confusion": confusion.tolist(),
    }


def evaluate(classifier: Any, bank: Bank) -> Dict[str, Any]:
    """:func:`scores` of ``classifier`` on ``bank``."""
    return scores(
        bank.y, predict(classifier, bank.x), [m.get("kind") for m in bank.meta]
    )


def evaluate_images(
    classifier: Any, images: np.ndarray, y: np.ndarray
) -> Dict[str, Any]:
    """:func:`scores` on images already framed for the model (MNIST)."""
    if not len(y):
        return scores(y, y)
    return scores(y, predict_images(classifier, images).argmax(axis=1))
