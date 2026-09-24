"""Score ``process_copy.ink_grades`` against real graded copies.

Development tool, not part of the test suite: it needs real copies, which do
not belong in the repository. It answers the only question that matters before
this feature is wired into the pipeline -- how often the grade written on the
page is read correctly, and whether a misread shows up as low confidence
rather than as a confident wrong number.

Two shapes of input:

* ``--copies DIR --notes CSV`` -- whole graded copies, one file per student,
  sliced into questions with ``utils.split.calculate_pages`` (the same
  arithmetic production uses), labelled from a Moodle export whose ``Q<n>``
  columns hold the confirmed grades.
* ``--questions DIR`` -- the per-question tree ``Q<n>/<copy>_Q<n>.pdf`` that
  the re-upload flow produces, where the grade is on page 0. Labels come from
  ``--labels`` (``{"Q1": {"<file stem>": 9.0}}``); without it the readings are
  printed for review, which is how a label file gets written in the first
  place.

Usage:
    python tools/score_ink_grades.py --copies examples/copies \\
        --notes examples/notes.csv \\
        --layout Q1:4:11,Q2:3:9,Q3:5:12,Q4:4:12,Q5:5:11,Q6:3:2
    python tools/score_ink_grades.py --questions storage/documents/<job_id> \\
        --max-points 9 --labels corpus_b.json
"""

import argparse
import contextlib
import csv
import io
import json
import os
import re
import sys
from collections import defaultdict
from typing import Dict, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
EXECUTOR = os.path.dirname(HERE)
sys.path.insert(0, EXECUTOR)
sys.path.insert(0, os.path.join(EXECUTOR, "python"))
sys.path.insert(0, os.path.join(os.path.dirname(EXECUTOR), "common"))

import pymupdf  # noqa: E402

from process_copy import ink_grades  # noqa: E402
from utils.split import calculate_pages  # noqa: E402

MATRICULE_IN_NAME = re.compile(r"_(\d{7})\.pdf$")
THRESHOLDS = (0.0, 0.80, 0.90, 0.95, 0.99)


def parse_layout(text: str) -> Tuple[Dict[str, int], Dict[str, float]]:
    """``"Q1:4:11,Q2:3:9"`` into pages-per-question and max-points maps."""
    pages, points = {}, {}
    for item in text.split(","):
        key, n_pages, n_points = item.split(":")
        pages[key] = int(n_pages)
        points[key] = float(n_points)
    return pages, points


def load_notes(path: str) -> Dict[str, Dict[str, float]]:
    """``{matricule: {"Q1": grade, ...}}`` from a Moodle export."""
    notes: Dict[str, Dict[str, float]] = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            matricule = (row.get("Matricule") or "").strip()
            if not matricule:
                continue
            grades = {}
            for key, value in row.items():
                if key and re.fullmatch(r"Q\d+", key) and (value or "").strip():
                    grades[key] = float(value.replace(",", "."))
            if grades:
                notes[matricule] = grades
    return notes


@contextlib.contextmanager
def quiet():
    """Swallow the recogniser's per-call prints; a batch is thousands of lines."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        yield


def read_page(page, max_points, modal, classifier, bonus=False):
    """One page through the candidate pipeline."""
    with quiet():
        candidates = ink_grades.grade_candidates(page, max_points)
        reading = ink_grades.pick(candidates, modal, max_points, classifier, bonus)
    return candidates, reading


def collect(pages_by_question, max_points_map, classifier, bonus_keys):
    """Two passes: learn where the grades sit, then read them.

    The modal position is learned from the pages that gave a single candidate,
    per question, exactly as the executor will do per upload batch.
    """
    candidates_by_question = defaultdict(list)
    keep = {}
    for question, entries in pages_by_question.items():
        for label, page in entries:
            with quiet():
                cands = ink_grades.grade_candidates(page, max_points_map.get(question))
            candidates_by_question[question].append(cands)
            keep[(question, label)] = cands

    modal = ink_grades.learn_modal_positions(candidates_by_question)

    results = []
    for (question, label), cands in keep.items():
        with quiet():
            reading = ink_grades.pick(
                cands,
                modal.get(question),
                max_points_map.get(question),
                classifier,
                question in bonus_keys,
            )
        results.append((question, label, reading))
    return results, modal


def report(results, truth, modal, dump=None):
    """Per-question accuracy, the confidence/coverage table and the confusions."""
    per_question = defaultdict(lambda: [0, 0])
    confusions = defaultdict(int)
    scored = []
    unlabelled = 0

    for question, label, reading in results:
        if (question, label) not in truth:
            unlabelled += 1
            continue
        expected = truth[(question, label)]
        if expected is None:
            # labelled "nothing written here": reporting a value is the error
            ok = reading.grade is None
        else:
            ok = reading.grade is not None and abs(reading.grade - expected) < 1e-6
        per_question[question][1] += 1
        per_question[question][0] += int(ok)
        scored.append((reading.confidence, ok))
        if not ok:
            confusions[(reading.grade, expected, reading.reason)] += 1
            if dump:
                print(
                    f"    MISS {question} {label}: read {reading.grade} "
                    f"expected {expected} ({reading.reason}, "
                    f"conf {reading.confidence:.2f})"
                )

    total = sum(n for _, n in per_question.values())
    good = sum(g for g, _ in per_question.values())
    print(
        f"\nscored {total} pages"
        + (f" ({unlabelled} unlabelled)" if unlabelled else "")
    )
    if not total:
        return 0.0
    print("\nper question:")
    for question in sorted(per_question, key=lambda q: int(q[1:])):
        g, n = per_question[question]
        centre = modal.get(question)
        where = f"modal ({centre[0]:.2f}, {centre[1]:.2f})" if centre else "no prior"
        print(f"  {question}: {g:3d}/{n:3d}  {100 * g / n:5.1f}%   {where}")
    print(f"\noverall: {good}/{total} = {100 * good / total:.1f}%")

    print("\nconfidence gate:")
    print("  threshold  prefilled   precision")
    for threshold in THRESHOLDS:
        kept = [ok for conf, ok in scored if conf >= threshold]
        if not kept:
            continue
        coverage = 100 * len(kept) / len(scored)
        precision = 100 * sum(kept) / len(kept)
        print(f"     {threshold:.2f}      {coverage:5.1f}%      {precision:5.1f}%")

    if confusions:
        print("\nconfusions (read -> expected, reason, count):")
        for (got, want, reason), count in sorted(
            confusions.items(), key=lambda kv: -kv[1]
        ):
            print(f"  {got} -> {want}  [{reason}] x{count}")
    return 100 * good / total


def run_copies(args, classifier):
    """Whole graded copies sliced with the production page arithmetic."""
    pages_map, points = parse_layout(args.layout)
    slices = calculate_pages(pages_map)
    notes = load_notes(args.notes)
    bonus = set(args.bonus.split(",")) if args.bonus else set()

    pages_by_question = defaultdict(list)
    truth = {}
    docs = []
    for name in sorted(os.listdir(args.copies)):
        if not name.endswith(".pdf"):
            continue
        match = MATRICULE_IN_NAME.search(name)
        if not match:
            continue
        matricule = match.group(1)
        doc = pymupdf.open(os.path.join(args.copies, name))
        docs.append(doc)
        for question, page_numbers in slices.items():
            first = page_numbers[0]
            if first >= doc.page_count:
                continue
            pages_by_question[question].append((matricule, doc[first]))
            expected = notes.get(matricule, {}).get(question)
            if expected is not None:
                truth[(question, matricule)] = expected

    results, modal = collect(pages_by_question, points, classifier, bonus)
    accuracy = report(results, truth, modal, args.dump_failures)
    for doc in docs:
        doc.close()
    return accuracy


def run_questions(args, classifier):
    """The per-question tree, where every grade is on page 0."""
    labels = json.load(open(args.labels)) if args.labels else {}
    bonus = set(args.bonus.split(",")) if args.bonus else set()
    points = {}
    pages_by_question = defaultdict(list)
    truth = {}
    docs = []

    for question in sorted(os.listdir(args.questions)):
        folder = os.path.join(args.questions, question)
        if not re.fullmatch(r"Q\d+", question) or not os.path.isdir(folder):
            continue
        points[question] = args.max_points
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".pdf"):
                continue
            stem = name[: -len(".pdf")]
            doc = pymupdf.open(os.path.join(folder, name))
            docs.append(doc)
            pages_by_question[question].append((stem, doc[0]))
            if stem in labels.get(question, {}):
                value = labels[question][stem]
                truth[(question, stem)] = None if value is None else float(value)

    results, modal = collect(pages_by_question, points, classifier, bonus)

    if not labels:
        print("no --labels: readings for review\n")
        for question, label, reading in sorted(results):
            print(
                f"  {question} {label:26s} grade={reading.grade} "
                f"conf={reading.confidence:.2f} src={reading.source} "
                f"reason={reading.reason} cands={reading.n_candidates}"
            )
        for doc in docs:
            doc.close()
        return 100.0

    accuracy = report(results, truth, modal, args.dump_failures)
    for doc in docs:
        doc.close()
    return accuracy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--copies", help="folder of whole graded copies")
    parser.add_argument("--notes", help="Moodle export labelling --copies")
    parser.add_argument(
        "--layout",
        default="Q1:4:11,Q2:3:9,Q3:5:12,Q4:4:12,Q5:5:11,Q6:3:2",
        help="Q<n>:<pages>:<max points>, comma separated",
    )
    parser.add_argument("--questions", help="folder holding Q1/, Q2/, ... ")
    parser.add_argument("--max-points", type=float, default=9.0)
    parser.add_argument("--labels", help="json labels for --questions")
    parser.add_argument("--bonus", help="comma separated bonus question keys")
    parser.add_argument("--model", help="classifier file (.tflite or .h5)")
    parser.add_argument("--dump-failures", action="store_true")
    parser.add_argument("--min-accuracy", type=float, default=0.0)
    args = parser.parse_args()

    classifier = load_classifier(args.model)

    if args.copies:
        accuracy = run_copies(args, classifier)
    elif args.questions:
        accuracy = run_questions(args, classifier)
    else:
        parser.error("one of --copies or --questions is required")

    return 0 if accuracy >= args.min_accuracy else 1


def load_classifier(path: Optional[str]):
    """The LiteRT classifier, or a Keras model when one is named directly.

    The executor ships only the ``.tflite``; allowing the ``.h5`` here keeps the
    tool usable in a development environment that has TensorFlow but not the
    LiteRT wheel, and the two agree to 1e-7 by construction.
    """
    if path and path.endswith(".h5"):
        from tensorflow.keras.models import load_model

        return load_model(path)
    from process_copy.classifier import load_classifier as load

    return load(path)


if __name__ == "__main__":
    sys.exit(main())
