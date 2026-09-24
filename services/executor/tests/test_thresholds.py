"""The digit threshold on degraded prints (glued dot), the framing margins given
to the model and the known confusions."""

import cv2
import numpy as np

from process_copy import digits, recognize


def two_digits(bridge=None):
    """Two black 30 x 50 strokes 12 px apart on white; ``bridge`` fills the gap
    with that gray level (the halo of a degraded print)."""
    img = np.full((100, 200), 255, np.uint8)
    img[25:75, 50:80] = 0
    img[25:75, 92:122] = 0
    if bridge is not None:
        img[60:75, 80:92] = bridge
    return img


def test_separate_strokes_keep_the_permissive_threshold():
    thresh = recognize.get_clean_thresh(two_digits())
    assert len(recognize.ink_rects(thresh)) == 2


def test_light_gray_bridge_is_ink_under_the_fixed_threshold_only():
    # 180 is ink for the fixed threshold at 200 but not for Otsu
    plain = cv2.threshold(
        cv2.GaussianBlur(two_digits(bridge=180), (5, 5), 0),
        200,
        255,
        cv2.THRESH_BINARY_INV,
    )[1]
    assert len(recognize.ink_rects(plain)) == 1  # glued into one wide blob
    thresh = recognize.get_clean_thresh(two_digits(bridge=180))
    assert len(recognize.ink_rects(thresh)) == 2  # the retry split it


def test_faint_single_stroke_is_not_dropped():
    # a faint handwritten digit (gray 180) alone is taller than wide: no retry,
    # and the permissive threshold keeps it
    img = np.full((100, 200), 255, np.uint8)
    img[25:75, 60:90] = 180
    thresh = recognize.get_clean_thresh(img)
    assert len(recognize.ink_rects(thresh)) == 1


def test_a_truly_wide_stroke_is_kept_when_otsu_splits_nothing():
    img = np.full((100, 200), 255, np.uint8)
    img[30:70, 40:160] = 0  # one solid wide blob (Otsu changes nothing)
    thresh = recognize.get_clean_thresh(img)
    assert len(recognize.ink_rects(thresh)) == 1


class SevenClassifier:
    """A model that always answers 7."""

    def predict(self, roi, verbose=0):
        out = np.zeros((1, 10), np.float32)
        out[0, 7] = 1.0
        return out


def test_known_confusion_adds_the_other_digit_with_probability_zero():
    gray = np.full((60, 40), 255, np.uint8)
    gray[10:50, 15:25] = 0
    thresh = recognize.get_clean_thresh(gray)
    cnts, _ = cv2.findContours(
        thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    candidates = recognize.extract_digit(cnts[0], gray, thresh, SevenClassifier())
    assert candidates[0][1] == 7
    assert (0, 1) in [(float(p), i) for p, i in candidates]


class FramingClassifier:
    """Answers 4 for the first framing of the batch and 9 for the second."""

    def __init__(self):
        self.batches = []

    def predict(self, batch, verbose=0):
        self.batches.append(batch.shape)
        out = np.zeros((batch.shape[0], 10), np.float32)
        out[0, 4] = 1.0
        out[1:, 9] = 1.0
        return out


def test_digit_probabilities_are_averaged_over_the_framing_margins(monkeypatch):
    monkeypatch.setattr(digits, "digit_margins", [0.1, 0.25])
    gray = np.full((60, 40), 255, np.uint8)
    gray[10:50, 15:25] = 0
    thresh = recognize.get_clean_thresh(gray)
    cnts, _ = cv2.findContours(
        thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    classifier = FramingClassifier()
    candidates = recognize.extract_digit(cnts[0], gray, thresh, classifier)
    assert classifier.batches == [(2, 28, 28, 1)]  # one call, one row per margin
    assert sorted((round(float(p), 2), d) for p, d in candidates) == [
        (0.5, 4),
        (0.5, 9),
    ]


def test_confusion_table_of_the_matricule_is_separate():
    gray = np.full((60, 40), 255, np.uint8)
    gray[10:50, 15:25] = 0
    thresh = recognize.get_clean_thresh(gray)
    cnts, _ = cv2.findContours(
        thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    classifier = SevenClassifier()

    def digits(**kwargs):
        return [
            d
            for _, d in recognize.extract_digit(
                cnts[0], gray, thresh, classifier, **kwargs
            )
        ]

    assert digits() == [7, 1]  # config.known_mistmatch
    assert digits(confusions={7: 4}) == [7, 4]
    assert digits(confusions={}) == [7]
