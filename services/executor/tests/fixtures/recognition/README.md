# Recognition fixtures

Real scanned boxes on which `tests/test_recognition.py` runs the digit
recogniser end to end (Keras model `digit_recognizer.h5`, OpenCV box and
contour detection).

- `grades_*.png`: the "Réservé" grade table of a cover page, cropped exactly
  as `fetch_box(page, grade_box)` does at 300 dpi (357 x 1320 px). The
  printed digits come from the grade overlay the executor writes on finalised
  copies; `grades_blank.png` is a cover page scanned before grading and
  `grades_overlapping_overlays.png` has two overlays printed on top of each
  other, which the total check must reject.
- `matricule_*.png`: the identification table of a cover page, cropped as
  `fetch_box(page, matricule_box)` (2040 x 660 px), with the interior of the
  name, first-name and signature cells painted white (the table lines are
  kept: the detection walks the cells of the biggest contour). The seven
  handwritten digits of the matricule remain.
- `expected.json`: the page shape and boxes the crops were taken with, and
  for each crop the value the recogniser must return. `matricules[].known_miss`
  marks pages the current model misreads (kept so an improvement shows up as
  an unexpected pass, not so the misread is asserted).

The test pastes each crop at its box position on a blank 2550 x 3300 page and
calls `grade()` / `find_matricule()` as `grade_files` and `find_matricules`
do, so the fixtures never hold more than the box regions.

`build_fixtures.py` regenerates everything from a local storage tree and the
MongoDB of the compose stack (`STORAGE`, `MONGODB_USER`, `MONGODB_PASSWORD`);
it is not run by the tests.
