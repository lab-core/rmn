"""The digit threshold on degraded prints (glued dot) and the known confusions."""

import cv2
import numpy as np

from process_copy import recognize


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
