"""From a contour to a number: the classifier, and what may follow a decimal point."""

import random
import cv2
import numpy as np
from process_copy import digit_bank
from process_copy.classifier import load_classifier
from process_copy.config import (
    allowed_decimals,
    digit_margins,
    known_mistmatch,
)
from process_copy.imaging import imwrite_png, make_square
from process_copy.contours import find_digit_contours







def extract_digit(cnt, gray, thresh, classifier, threshold=1e-2, border=7, confusions=None):
    """Candidates ``(probability, digit)`` of the digit drawn by contour ``cnt``.

    ``confusions`` maps a digit the model confuses to the digit it may be
    (``config.known_mistmatch`` by default, the matricule table for a matricule);
    the latter is appended with probability 0 when the former is a candidate.
    """
    if confusions is None:
        confusions = known_mistmatch
    # creating a mask
    mask = np.zeros(gray.shape, dtype="uint8")
    (x, y, w, h) = cv2.boundingRect(cnt)
    # print("bounding box: [", x, ",", x+w, "] x [", y, ",", y+h, "]")

    hull = cv2.convexHull(cnt)
    cv2.drawContours(mask, [hull], -1, 255, -1)
    mask = cv2.bitwise_and(thresh, thresh, mask=mask)

    # Getting Region of interest
    roi = mask[
        max(0, y - border) : min(mask.shape[0], y + h + border),
        max(0, x - border) : min(mask.shape[1], x + w + border),
    ]
    imwrite_png("roi", roi)

    # The model was trained on MNIST (digit in about 70% of the frame) mixed
    # with a dataset whose digits fill it, so no single framing matches the
    # training data: predict the digit framed with each margin of
    # config.digit_margins and average the probabilities.
    squares = [make_square(roi, margin=m) for m in digit_margins]
    imwrite_png("roi2", squares[0])
    # the crop as it is, for the bank: the framings above are a training-time
    # choice and must not be baked into what is stored (see digit_bank)
    digit_bank.record(roi)

    # predicting
    batch = np.stack(squares).reshape(len(squares), 28, 28, 1).astype("float32") / 255
    pproba = classifier.predict(batch, verbose=0).mean(axis=0)
    predict = [(p, i) for i, p in enumerate(pproba)]
    predict = sorted(predict, reverse=True)
    cumul = 0
    d = []
    for p, i in predict:
        d.append((p, i))
        cumul += p
        if cumul > 1 - threshold:
            break

    # find known mismatch, and add it with probability 0
    for k, v in confusions.items():
        numbs = [i for p, i in d]
        if k in numbs and v not in numbs:
            d.append((0, v))

    return d




def extract_all_digits(cnts, gray, thresh, classifier, threshold=1e-2, border=7, confusions=None):
    all_digits = []
    for c in cnts:
        try:
            d = extract_digit(c, gray, thresh, classifier, threshold, border, confusions)
            all_digits.append((c, d))
        except Exception as e:
            print(e)
    return all_digits




def split_digits(digits, dot):
    """The integer and decimal digit strings of a recognised digit sequence."""
    number = "".join("%d" % d[1] for d in digits[:dot])
    decimals = "".join("%d" % d[1] for d in digits[dot:])
    return number, decimals




def extract_number(digits, dot, just_allowed_decimals=False):
    """The number written by a digit sequence, or None when its decimals are
    checked (``just_allowed_decimals``) and not allowed."""
    number, decimals = split_digits(digits, dot)
    if just_allowed_decimals and decimals and decimals not in allowed_decimals:
        return None
    return float("%s.%s" % (number, decimals or "0"))




def allowed_decimals_with_digits(n_digits, allowed=None):
    """Allowed decimal parts written with ``n_digits`` digits, "0" excluded.

    A recognised non-zero digit is a fraction the student wrote: it is never
    turned into a whole number.
    """
    allowed = allowed_decimals if allowed is None else allowed
    return [d for d in allowed if len(d) == n_digits and int(d) != 0]




def random_allowed_decimals(recognised, allowed=None, rng=random):
    """An allowed decimal part for a recognised one that is not allowed.

    Drawn at random among the allowed parts with the same number of digits
    (``config.allowed_decimals``). When none has that many digits, the allowed
    part closest in value is used. An empty or allowed part is returned as is.
    """
    allowed = allowed_decimals if allowed is None else allowed
    if not recognised or recognised in allowed:
        return recognised
    same_length = allowed_decimals_with_digits(len(recognised), allowed)
    if same_length:
        chosen = rng.choice(same_length)
    else:
        value = float("0." + recognised)
        chosen = min(allowed, key=lambda d: abs(float("0." + d) - value))
    print("Corrected decimals", recognised, "->", chosen)
    return chosen




def process_digits_combinations(all_digits, dot):
    # create all combinations
    combinations = [(0, [])]
    # check if finding the question total (e.g., / 5) in the box if present.
    # it should recognize / as number 1.
    # We just cut all numbers at that point if any
    trunc_combinations = []
    j = 0
    for (c, d) in all_digits:
        for (p, i) in d:
            # check if a 1 not in first position and after dot if any
            # check if neither first and last digit and not first digit after the dot if any
            if i == 1 and 0 < j < len(all_digits) - 1 and (dot >= len(all_digits) or j > dot):
                # give a bonus to the truncated number as generally more probable
               trunc_combinations += [
                   (cumul + j*p, digits)
                   for (cumul, digits) in combinations
               ]
        # add every possible combinations
        combinations = [
            (cumul + p, digits + [(c, i)])
            for (p, i) in d
            for (cumul, digits) in combinations
        ]
        j += 1
    combinations += trunc_combinations
    print("Combinations:", [(p, [i for (c, i) in d]) for (p, d) in combinations])

    # process all combinations by decreasing probability: normalize the
    # probability and keep the numbers whose decimal part is allowed
    numbers = []
    just_allowed_decimals = len(trunc_combinations) == 0
    ranked = sorted(combinations, key=lambda c: c[0] / len(c[1]), reverse=True)
    for p, digits in ranked:
        number = extract_number(digits, dot, just_allowed_decimals)
        if number is not None:
            numbers.append((p / len(digits), number))

    if not numbers and just_allowed_decimals and ranked:
        # no combination has an allowed decimal part: keep the most probable
        # digits and draw an allowed decimal part of the same length
        p, digits = ranked[0]
        integer, decimals = split_digits(digits, dot)
        decimals = random_allowed_decimals(decimals)
        numbers.append((p / len(digits), float("%s.%s" % (integer, decimals or "0"))))

    if not numbers:
        return [(1.0, 0)]

    return sorted(numbers, reverse=True)




def correct_decimals(p, allowed=None, rng=random):
    """Make the decimal part of a grade allowed after the dot was moved.

    Same rule as the recognition: an allowed decimal part is kept, another is
    replaced by a random allowed part with the same number of digits (see
    ``config.allowed_decimals``).
    """
    number, _, decimals = f"{p:.10f}".rstrip("0").partition(".")
    decimals = random_allowed_decimals(decimals, allowed, rng)
    n = float("%s.%s" % (number, decimals or "0"))
    print("Correct decimals:", p, "->", n)
    return n




def test(gray_img, classifier=None, trim=None, meta=None):
    """The numbers a box may hold, most probable first.

    ``meta`` is what the caller knows about the box (``box_index`` for the
    grade table); it is staged with the crops so a grade a human later
    confirms can be matched back to the digits that were read.
    """
    if classifier is None:
        classifier = load_classifier()

    # image copy
    gray = gray_img.copy()
    imwrite_png("gray", gray)

    with digit_bank.reading(**(meta or {})):
        # find contours of the numbers as well as the dot number position
        # return a sorted list of the relevant digits' contours and the dot position (and the threshold image used)
        cnts, dot, thresh = find_digit_contours(gray, trim=trim)

        # if found no digits contours, return 0
        if not cnts:
            return [(1.0, 0)]

        # extract digits
        all_digits = extract_all_digits(cnts, gray, thresh, classifier)

        if not all_digits:
            print("No valid number has been found")
            return [(1.0, 0)]

        print("All digits found:", [d[1] for d in all_digits])

        # the crops are the digits of this box, in order: worth keeping
        digit_bank.keep(dot=dot, read=most_probable_digits(all_digits))

        # process all possible digits combinations
        return process_digits_combinations(all_digits, dot)


def most_probable_digits(all_digits):
    """The digits the model ranks first, as a string, for the bank's metadata."""
    digits = []
    for entry in all_digits:
        candidates = entry[1] if isinstance(entry, tuple) else entry
        digits.append("%d" % max(candidates)[1] if candidates else "?")
    return "".join(digits)
