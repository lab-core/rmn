"""Regenerate the recognition fixtures from a local storage tree and MongoDB.

Run from services/executor with the test virtualenv:

    STORAGE=/path/to/storage MONGODB_USER=... MONGODB_PASSWORD=... \
        python tests/fixtures/recognition/build_fixtures.py

Every matricule crop is anonymised before it is written: the interior of the
name, first-name and signature cells of the identification table is painted
white, the table lines are kept. Review the images before committing them.
"""

import contextlib
import io
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

EXECUTOR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(EXECUTOR))
sys.path.insert(0, str(EXECUTOR / "python"))

from process_copy import recognize  # noqa: E402
from process_copy.config import grade_box, matricule_box  # noqa: E402

OUT = Path(__file__).resolve().parent
STORAGE = Path(os.environ["STORAGE"])
SHAPE = (2550, 3300)  # US letter at 300 dpi, as grade_files renders pages
GBOX = list(grade_box["exam"]["grade"])
MBOX = list(matricule_box["exam"]["front"])
RBOX = list(matricule_box["exam"]["regular"])

# (fixture name, path under the storage, note)
GRADE_CASES = [
    (
        "printed_ones",
        "cover_pages/fb9bdeea-eb0e-4f72-b7f6-80ff8ed72861/MTH1106_AUTOMNE_2025_CP1_GROUPE_2-33_cover.pdf",
        "five printed 1 and a printed total 5 (the grade overlay of a finalised task)",
    ),
    (
        "printed_with_zero",
        "documents/4e094d91-bbbf-44ea-96aa-d5e4a314ba7c/all/Justin_Dubois_2376663.pdf",
        "printed 0, 1, 1, 1, 1 and total 4",
    ),
    (
        "blank",
        "cover_pages/fb9bdeea-eb0e-4f72-b7f6-80ff8ed72861/MTH1106_AUTOMNE_2025_CP1_GROUPE_2-33_cover_nograde.pdf",
        "empty boxes: a cover page scanned before grading",
    ),
    (
        "overlapping_overlays",
        "documents/4e094d91-bbbf-44ea-96aa-d5e4a314ba7c/all/rtnebsv-0.pdf",
        "two grade overlays printed on top of each other: unreadable, the total check must reject it",
    ),
]
# job whose validated matricules are the ground truth, and the copies to use
MATRICULE_JOB = "6667a9b4-21b8-4450-ab6c-1e9e89537e38"
MATRICULE_COPIES = [
    "GROUPE_5-35",
    "GROUPE_8-28",
    "GROUPE_5-32",
    "GROUPE_7-54",
    "GROUPE_6-54",
    "GROUPE_5-5",
    "GROUPE_7-52",
    "GROUPE_3-16",
]


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def crop_of(rel_path, box):
    grays = quiet(
        recognize.gray_images,
        str(STORAGE / rel_path),
        [0],
        straighten=False,
        shape=SHAPE,
    )
    return recognize.fetch_box(grays[0], box)


def page_with(crop, box):
    """A blank page with ``crop`` pasted where ``box`` sits (what the test does)."""
    width, height = SHAPE
    page = np.full((height, width), 255, np.uint8)
    x1, y1 = int(box[0] * width), int(box[2] * height)
    page[y1 : y1 + crop.shape[0], x1 : x1 + crop.shape[1]] = crop
    return page


def table_lines(crop):
    """Positions of the identification table's lines (rows, columns)."""
    dark = crop < 128
    rows = np.where(dark.mean(axis=1) > 0.5)[0]
    band = dark[int(0.35 * crop.shape[0]) : int(0.75 * crop.shape[0])]
    cols = np.where(band.mean(axis=0) > 0.5)[0]

    def groups(indexes):
        out = []
        for i in indexes:
            if out and i - out[-1][-1] <= 3:
                out[-1].append(int(i))
            else:
                out.append([int(i)])
        return [int(np.mean(g)) for g in out]

    return groups(rows), groups(cols)


def anonymise(crop, margin=5):
    """White out the name, first-name and signature cells, keeping the lines."""
    h, w = crop.shape
    rows, cols = table_lines(crop)
    # the three horizontal lines of the two data rows, the left border, the
    # Nom|Prénom (and Signature|Matricule) separator and the right border
    top, middle, bottom = [y for y in rows if 0.3 * h < y < 0.72 * h][:3]
    left = min(x for x in cols if x > 0.01 * w)
    separator = min(cols, key=lambda x: abs(x - 0.27 * w))
    right = min(cols, key=lambda x: abs(x - 0.905 * w))
    out = crop.copy()
    out[top + margin : middle - margin, left + margin : right - margin] = (
        255  # Nom and Prénom
    )
    out[middle + margin : bottom - margin, left + margin : separator - margin] = (
        255  # Signature
    )
    return out


def main():
    from keras.models import load_model
    from pymongo import MongoClient

    classifier = load_model(str(EXECUTOR / "digit_recognizer.h5"))
    spec = {
        "page_shape": list(SHAPE),
        "grade_box": GBOX,
        "matricule_box": MBOX,
        "regular_matricule_box": RBOX,
        "grades": [],
        "matricules": [],
    }

    for name, rel, note in GRADE_CASES:
        crop = crop_of(rel, GBOX)
        cv2.imwrite(str(OUT / f"grades_{name}.png"), crop)
        matched, numbers, *_ = quiet(
            recognize.grade,
            page_with(crop, GBOX),
            GBOX,
            classifier=classifier,
            max_grade=30,
            max_question=12,
        )
        spec["grades"].append(
            {
                "file": f"grades_{name}.png",
                "note": note,
                "matched": bool(matched),
                "numbers": [float(n) for n in numbers],
            }
        )
        print(f"grades_{name}: matched={matched} numbers={numbers}")

    mongo = MongoClient(
        "mongodb://%s:%s@localhost:27017/"
        % (os.environ["MONGODB_USER"], os.environ["MONGODB_PASSWORD"])
    )
    docs = list(
        mongo["RMN"]["job_documents"].find(
            {"job_id": MATRICULE_JOB},
            {"_id": 0, "filename": 1, "matricule": 1, "rel_filepath": 1},
        )
    )
    for i, suffix in enumerate(MATRICULE_COPIES, start=1):
        doc = next(d for d in docs if d["filename"].endswith(suffix))
        crop = anonymise(crop_of(doc["rel_filepath"], MBOX))
        name = f"matricule_{i:02d}.png"
        cv2.imwrite(str(OUT / name), crop)
        found, *_ = quiet(
            recognize.find_matricule,
            [page_with(crop, MBOX)],
            MBOX,
            RBOX,
            classifier,
            [],
            separate_box=True,
        )
        expected = str(doc["matricule"])
        spec["matricules"].append(
            {"file": name, "matricule": expected, "known_miss": str(found) != expected}
        )
        print(f"{name}: expected={expected} found={found}")

    (OUT / "expected.json").write_text(json.dumps(spec, indent=2) + "\n")


if __name__ == "__main__":
    main()
