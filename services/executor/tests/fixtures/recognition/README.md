# Recognition fixtures

Real scanned boxes on which `tests/test_recognition.py` runs the digit
recogniser end to end (Keras model `digit_recognizer.h5`, OpenCV box and
contour detection).

- `grades_*.png`: the "Réservé" grade table of a cover page, cropped exactly
  as `fetch_box(page, grade_box)` does at 300 dpi (357 x 1320 px). The
  printed digits come from the grade overlay the executor writes on finalised
  copies; `grades_blank.png` is a cover page scanned before grading.
  `grades_dot_glued_to_digits.png` is a readable `3.0 / 1.0 / 1.0 / 1.0 / 1.0 /
  7.0` overlay whose jpeg-degraded dots touch the digits under the fixed
  threshold; it is read thanks to the Otsu retry of `get_clean_thresh` and the
  `7 -> 1` entry of `config.known_mistmatch`, and guards both.
  `grades_printed_decimals.png` is not a scan: the grades
  `5.3, 1.25, 2.75, 0.5, 0, 10` are printed on the blank table with the
  executor's own overlay writer and degraded like an overlay (jpeg quality 5),
  because no cover page of the storage carries a decimal grade. It checks the
  allowed-decimals rule on the recogniser: 5.3 is stored as 5.5, the quarter
  and half points are kept and the total matches only once 5.3 is corrected.
- `matricule_*.png`: the identification table of a cover page, cropped as
  `fetch_box(page, matricule_box)` (2040 x 660 px), with the interior of the
  name, first-name and signature cells painted white (the table lines are
  kept: the detection walks the cells of the biggest contour). The seven
  handwritten digits of the matricule remain.
- `expected.json`: the page shape and boxes the crops were taken with, and
  for each crop the value the recogniser must return. `known_miss` marks
  crops the current model misreads (xfail); when such a crop starts reading
  correctly the test fails until the flag is dropped, so the improvement is
  recorded rather than hidden.

The test pastes each crop at its box position on a blank 2550 x 3300 page and
calls `grade()` / `find_matricule()` as `grade_files` and `find_matricules`
do, so the fixtures never hold more than the box regions.

`build_fixtures.py` regenerates everything from a local storage tree and the
MongoDB of the compose stack (`STORAGE`, `MONGODB_USER`, `MONGODB_PASSWORD`);
it is not run by the tests.
