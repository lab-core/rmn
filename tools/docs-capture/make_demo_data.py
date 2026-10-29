"""Build the fictitious exam the screenshots of the user guide are made with.

The guide must never show a real student, so its copies are drawn here: the
default cover page and inner page of rmn (services/server/default_templates),
filled in with a handwriting font, invented names and matricules that no
student can have (2999xxx), then rasterised with a slight tilt and some noise
so that rmn reads them like scans.

Outputs, in the --out directory:

* ``copies-moodle.zip``: the copies as Moodle's "Télécharger tous les travaux
  remis" names them (case A of the guide);
* ``copies-scans.zip``: the same copies as a teacher's scanner names them
  (case B);
* ``formulaire-evaluation.csv``: the Moodle grading worksheet of the class,
  with one registered student who handed nothing in;
* ``grades.json``: the grade of each question of each copy, which the capture
  script types as a teacher would;
* ``page-de-garde.png``: a filled-in cover page, for the guide.

Usage::

    IMG=../../services/webapp/ng/src/assets/guide/img
    python make_demo_data.py --out demo --img-dir $IMG
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageFilter

REPO = Path(__file__).resolve().parents[2]
TEMPLATES = REPO / "services" / "server" / "default_templates"
COVER_PDF = TEMPLATES / "couverture" / "page_couverture_exam.pdf"
INNER_PDF = TEMPLATES / "interieur" / "template_exam.pdf"

# SIL Open Font License; downloaded on first use rather than committed
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/caveat/Caveat%5Bwght%5D.ttf"

# the boxes of the default templates, in PDF points (measured with PyMuPDF)
COVER_MATRICULE_X = [240.0, 260.7, 281.4, 302.1, 322.8, 343.5, 364.2]
COVER_MATRICULE_Y = (204.0, 220.0)
INNER_MATRICULE_X = [405.4, 426.7, 447.9, 469.2, 490.4, 511.7, 532.9]
INNER_MATRICULE_Y = (61.4, 85.3)
BOX_WIDTH = (17.0, 15.3)  # cover, inner

# the questions printed on the default cover page ("Réservé" column)
POINTS = [9, 8, 9, 10, 9]
DPI = 150

FIRST_NAMES = [
    "Camille",
    "Jules",
    "Inès",
    "Noah",
    "Zoé",
    "Hugo",
    "Maya",
    "Louis",
    "Rose",
]
LAST_NAMES = [
    "Démo",
    "Essai",
    "Modèle",
    "Fictif",
    "Exemple",
    "Prototype",
    "Simulé",
    "Brouillon",
    "Absent",
]
ANSWERS = [
    "On dérive puis on cherche les zéros de la dérivée.",
    "La série converge par le critère de comparaison.",
    "Par parties, en posant u égal au logarithme.",
    "Le volume se calcule avec la méthode des disques.",
    "La limite existe et vaut un demi.",
]


@dataclass
class Student:
    """A fictitious student of the demo class."""

    first: str
    last: str
    matricule: str
    participant: int
    group: str
    grades: list[float]

    @property
    def full_name(self) -> str:
        """The name as Moodle's "Nom complet" column writes it."""
        return f"{self.first} {self.last}"


def make_class(count: int, rng: random.Random) -> list[Student]:
    """Invent `count` students with copies, plus one who handed nothing in.

    Args:
        count: The number of students who sat the exam.
        rng: The random source, seeded for reproducible files.

    Returns:
        The students; the last one has no copy.
    """
    students = []
    for i in range(count + 1):
        grades = [float(rng.randint(max(0, p - 6), p)) for p in POINTS]
        students.append(
            Student(
                first=FIRST_NAMES[i % len(FIRST_NAMES)],
                last=LAST_NAMES[i % len(LAST_NAMES)],
                matricule=f"2999{rng.randint(0, 999):03d}",
                participant=17800000 + rng.randint(0, 99999),
                group="01" if i % 2 == 0 else "02",
                grades=grades,
            )
        )
    return students


def font_file(cache: Path) -> Path:
    """The handwriting font, downloaded into `cache` the first time.

    Args:
        cache: The directory that keeps the font between runs.

    Returns:
        The path of the TrueType file.
    """
    path = cache / "Caveat.ttf"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(FONT_URL, timeout=60) as response:
            path.write_bytes(response.read())
    return path


class Hand:
    """Writes on a PDF page like a student would: a bit off, a bit tilted."""

    def __init__(self, font: Path, rng: random.Random) -> None:
        """Hold the font and the random source.

        Args:
            font: The handwriting TrueType font.
            rng: The random source of the jitter.
        """
        self.font = str(font)
        self.rng = rng

    def write(
        self, page: fitz.Page, x: float, y: float, text: str, size: float = 16
    ) -> None:
        """Write `text` with its baseline at (x, y), with a little jitter.

        Args:
            page: The page to write on.
            x: The left of the text, in points.
            y: The baseline of the text, in points.
            text: What to write.
            size: The font size, in points.
        """
        page.insert_text(
            (x + self.rng.uniform(-1, 1), y + self.rng.uniform(-1, 1)),
            text,
            fontfile=self.font,
            fontname="caveat",
            fontsize=size * self.rng.uniform(0.95, 1.05),
            color=(0.1, 0.1, 0.1),
        )

    def digits(
        self,
        page: fitz.Page,
        boxes_x: list[float],
        box_y: tuple[float, float],
        width: float,
        number: str,
    ) -> None:
        """Write one digit per box, centred, as asked on the cover page.

        Args:
            page: The page to write on.
            boxes_x: The left edge of each box.
            box_y: The top and bottom of the row of boxes.
            width: The width of a box.
            number: The digits, one per box.
        """
        height = box_y[1] - box_y[0]
        for x, digit in zip(boxes_x, number):
            self.write(page, x + width * 0.28, box_y[1] - height * 0.12, digit, 19)


def cover_page(doc: fitz.Document, hand: Hand, student: Student) -> None:
    """Add the filled-in cover page of `student` to `doc`."""
    page = doc.new_page(width=612, height=792)
    page.show_pdf_page(page.rect, fitz.open(COVER_PDF), 0)
    hand.write(page, 90, 194, student.last, 15)
    hand.write(page, 228, 194, student.first, 15)
    hand.write(page, 446, 218, student.group, 15)
    hand.write(page, 112, 218, student.first[0] + ". " + student.last, 13)
    hand.digits(
        page, COVER_MATRICULE_X, COVER_MATRICULE_Y, BOX_WIDTH[0], student.matricule
    )


def question_page(
    doc: fitz.Document, hand: Hand, student: Student, question: int
) -> None:
    """Add the page of `question` (0-based) of `student`, not graded yet."""
    page = doc.new_page(width=612, height=792)
    page.show_pdf_page(page.rect, fitz.open(INNER_PDF), 0)
    # the inner template is a sample: its title and page number are replaced
    white = (1, 1, 1)
    page.draw_rect(fitz.Rect(60, 104, 260, 122), color=white, fill=white)
    page.draw_rect(fitz.Rect(510, 28, 552, 42), color=white, fill=white)
    page.insert_text(
        (63.8, 117.5),
        f"Question {question + 1} [{POINTS[question]} points]",
        fontname="tibo",
        fontsize=11,
    )
    page.insert_text((516.4, 38), f"page {question + 2}", fontname="tiit", fontsize=9)
    hand.digits(
        page, INNER_MATRICULE_X, INNER_MATRICULE_Y, BOX_WIDTH[1], student.matricule
    )
    # five words a line, as on a sheet of paper
    words = ANSWERS[question].split()
    lines = [" ".join(words[i:][:5]) for i in range(0, len(words), 5)]
    for i, line in enumerate(lines):
        hand.write(page, 80, 200.0 + 34 * i, line, 17)


def scanned(doc: fitz.Document, rng: random.Random) -> bytes:
    """Rasterise `doc` like a scanner would: grey, slightly tilted and blurred.

    Args:
        doc: The clean copy.
        rng: The random source of the tilt.

    Returns:
        The bytes of the scanned PDF.
    """
    out = fitz.open()
    for page in doc:
        pix = page.get_pixmap(dpi=DPI, colorspace=fitz.csGRAY)
        image = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        image = image.rotate(rng.uniform(-0.6, 0.6), fillcolor=255, expand=False)
        image = image.filter(ImageFilter.GaussianBlur(0.4))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80)
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, stream=buffer.getvalue())
    return out.tobytes(deflate=True)


def worksheet(path: Path, students: list[Student]) -> None:
    """Write the Moodle grading worksheet of the class, as Moodle exports it.

    Args:
        path: The csv file to write.
        students: The class; the last student handed nothing in.
    """
    header = [
        "Identifiant",
        "Nom complet",
        "Matricule",
        "Adresse de courriel",
        "Groupe",
        "Statut",
        "Note",
        "Note maximale",
        "La note peut être modifiée",
        "Dernière modification (travail remis)",
        "Dernière modification (note)",
        "Commentaires de feedback",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for i, student in enumerate(students):
            handed_in = i < len(students) - 1
            writer.writerow(
                [
                    f"Participant{student.participant}",
                    student.full_name,
                    student.matricule,
                    f"{student.first.lower()}.{student.last.lower()}@exemple.invalid",
                    student.group,
                    "Remis pour évaluation" if handed_in else "Aucune remise",
                    "",
                    f"{sum(POINTS)},00",
                    "Oui",
                    "lundi 26 octobre 2026, 10:12" if handed_in else "-",
                    "-",
                    "",
                ]
            )


def main() -> None:
    """Build the demo files."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    here = Path(__file__).resolve().parent
    parser.add_argument("--out", type=Path, default=here / "demo")
    parser.add_argument("--img-dir", type=Path, default=None)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    hand = Hand(font_file(here / ".cache"), rng)
    students = make_class(args.count, rng)

    moodle = zipfile.ZipFile(args.out / "copies-moodle.zip", "w")
    scans = zipfile.ZipFile(args.out / "copies-scans.zip", "w")
    with moodle, scans:
        for i, student in enumerate(students[:-1]):
            doc = fitz.open()
            cover_page(doc, hand, student)
            for question in range(len(POINTS)):
                question_page(doc, hand, student, question)
            if i == 0 and args.img_dir:
                args.img_dir.mkdir(parents=True, exist_ok=True)
                doc[0].get_pixmap(dpi=80).save(args.img_dir / "page-de-garde.png")
            pdf = scanned(doc, rng)
            folder = f"{student.full_name}_{student.participant}_assignsubmission_file_"
            moodle.writestr(f"{folder}/examen.pdf", pdf)
            scans.writestr(f"scan_{i + 1:03d}.pdf", pdf)
    worksheet(args.out / "formulaire-evaluation.csv", students)
    grades = {s.matricule: s.grades for s in students[:-1]}
    (args.out / "grades.json").write_text(json.dumps(grades, indent=1))
    print(f"{len(students) - 1} copies and the worksheet written to {args.out}")


if __name__ == "__main__":
    main()
