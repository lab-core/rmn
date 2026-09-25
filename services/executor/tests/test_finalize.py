"""Finalizing a validated job: grades csv, graded cover pages, zips and statistics.

The job is built the way the executor builds it: scanned copies split by
``split_and_save``, so the grades are really written on the cover pages and
the copies really merged. Only pdflatex is replaced (``fake_pdflatex``): the
stand-in writes, as the "pdf", the LaTeX inputs it was given, so every stats
page can be traced back to the student and the numbers it was compiled with.
"""

import json
import shutil
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest
from pypdf import PdfReader

import tasks.dispatch as dispatch
import tasks.finalize as finalize
from process_copy.database import Database
from rmn_common.moodle import MoodleFields as MF
from utils import stats
from utils.split import split_and_save
from utils.stop_handler import StopHandler
from utils.storage import Storage

EXECUTOR = Path(__file__).resolve().parent.parent
SPEC = json.loads(
    (EXECUTOR / "tests" / "fixtures" / "recognition" / "expected.json").read_text()
)
GRADE_BOX = SPEC["grade_box"]

# grades_blank.png has 6 boxes: 5 questions and the total. Q2 is ignored (0
# page) and Q5 is a bonus; the points are stored out of order on purpose.
PAGES = [["Q1", 1], ["Q2", 0], ["Q3", 1], ["Q4", 1], ["Q5", 1]]
POINTS = [["Q3", 5], ["Q1", 5], ["Q5", 2], ["Q2", 0], ["Q4", 5]]
BONUS = [["Q5", True], ["Q1", False], ["Q2", False], ["Q3", False], ["Q4", False]]

ROSTER = pd.DataFrame(
    {
        MF.id: [
            "Participant 101",
            "Participant 102",
            "Participant 103",
            "Participant 105",
        ],
        MF.name: ["Martin Alice", "Roy Bob", "Tremblay Carol", "Gagnon Eve"],
        MF.mat: ["1111111", "2222222", "3333333", "5555555"],
        "Groupe": ["A", "A", "B", "B"],
        MF.grade: [None, None, None, 12.0],
        MF.max: [15, 15, 15, 15],
        MF.mdate: ["-", "-", "-", "lundi 01 septembre 2026, 10:00"],
    }
)

ALICE_MOODLE_FOLDER = "Martin Alice_101_1111111_assignsubmission_file_/"

# filename -> (matricule, grades by template position, status)
COPIES = {
    "alice": ("1111111", [3, None, 2.5, 1, 1.5], "VALIDATED"),
    "bob": ("2222222", [None] * 5, "DELETED"),
    "carol": ("3333333", [4, None, 0, 2, None], "VALIDATED"),
    "dave": ("4444444", [1, None, 1, 1, 1], "VALIDATED"),  # not in the roster
}


@pytest.fixture
def fake_pdflatex(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the pdflatex run; return the list of the compiled inputs."""
    compiled = []

    def compile_tex(
        latex_file: str | Path,
        tmp_dir: str | Path,
        latex_cmd: str = "pdflatex",
        timeout: float | None = 5,
    ) -> str:
        tmp_dir = Path(tmp_dir)
        text = (tmp_dir / "data.tex").read_text() + (tmp_dir / "stats.tex").read_text()
        (tmp_dir / "main.pdf").write_text(text)
        compiled.append(text)
        return "main.pdf"

    monkeypatch.setattr(stats, "create_tex_pdf", compile_tex)
    return compiled


def _store_roster(storage_root: Path, roster: pd.DataFrame = ROSTER) -> str:
    path = storage_root / "output_csv" / "job.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    roster.to_csv(path, index=False)
    return "output_csv/job.csv"


def _job(
    mongo_db: Any,
    storage_root: Path,
    points: list = POINTS,
    pages: list = PAGES,
    bonus: list = BONUS,
    moodle: bool = True,
    student_stats: bool = True,
    roster: pd.DataFrame = ROSTER,
) -> dict:
    """Record a validated job, its template, its owner and its roster csv."""
    job = {
        "job_id": "job",
        "user_id": "teacher",
        "job_status": "VALIDATED",
        "n_pages_per_question": pages,
        "n_max_points_per_question": points,
        "bonus_enabled_map": bonus,
        "statistics_for_students": student_stats,
        "front_template_id": "front",
        "regular_template_id": None,
    }
    mongo_db["eval_jobs"].insert_one(dict(job))
    mongo_db["template"].insert_one({"template_id": "front", "grade_box": GRADE_BOX})
    mongo_db["users"].insert_one(
        {"username": "teacher", "moodleStructureInd": "1" if moodle else "0"}
    )
    mongo_db["jobs_output"].insert_one(
        {
            "job_id": "job",
            "user_id": "teacher",
            "notes_csv_file_id": _store_roster(storage_root, roster),
        }
    )
    return job


def _split_copies(
    tmp_path: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    copies: dict = COPIES,
) -> None:
    """Upload the copies as the executor does, then record their validation."""
    n_question_pages = sum(p for _, p in PAGES)
    paths = [
        str(
            scanned_copy_factory(
                tmp_path / "upload" / f"{name}.pdf",
                [("grades_blank.png", GRADE_BOX)],
                n_question_pages,
            )
        )
        for name in copies
    ]
    generated, errors = split_and_save(dict(PAGES), paths, "job")
    assert errors == []
    for name, (matricule, grades, status) in copies.items():
        mongo_db["job_documents"].update_one(
            {"job_id": "job", "filename": name},
            {"$set": {"matricule": matricule, "grades": grades, "status": status}},
        )


def _finalize(job: dict, tmp_path: Path, stop: Any = None) -> MagicMock:
    sio = MagicMock()
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    db = Database()
    stop_handler = stop or StopHandler(db.eval_jobs_collection(), job["job_id"])
    finalize.finalize_job(db, Storage(), sio, job, work, stop_handler)
    return sio


def _statuses(sio: MagicMock) -> list[str]:
    return [
        json.loads(c.args[1])["status"]
        for c in sio.emit.call_args_list
        if c.args[0] == "job_status"
    ]


def _zip_names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as z:
        return {n for n in z.namelist() if not n.endswith("/")}


def _read_zip(path: Path, name: str) -> bytes:
    with zipfile.ZipFile(path) as z:
        return z.read(name)


def _grades_csv(storage_root: Path) -> pd.DataFrame:
    return pd.read_csv(
        storage_root / "output_csv" / "job.csv", index_col=MF.mat, dtype={MF.mat: str}
    )


# ------------------------------------------------------------ the whole job


def test_finalized_job_writes_the_grades_csv_with_active_questions_only(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    fake_pdflatex: list[str],
) -> None:
    job = _job(mongo_db, storage_root)
    _split_copies(tmp_path, mongo_db, scanned_copy_factory)

    _finalize(job, tmp_path)

    df = _grades_csv(storage_root)
    assert [c for c in df.columns if c.startswith("Q")] == [
        "Q1",
        "Q3",
        "Q4",
        "Q5",
    ]  # Q2 is ignored
    alice = df.loc["1111111"]
    assert [alice[q] for q in ("Q1", "Q3", "Q4", "Q5")] == [3, 2.5, 1, 1.5]
    assert alice[MF.grade] == 8.0  # the bonus counts in the student's grade
    assert alice["index"] == 1  # document_index + 1
    assert alice[MF.mdate] != "-"
    carol = df.loc["3333333"]
    assert [carol[q] for q in ("Q1", "Q3", "Q4", "Q5")] == [
        4,
        0,
        2,
        0,
    ]  # a missing grade is 0
    assert carol[MF.grade] == 6.0
    # a deleted copy and a student without a copy keep the roster values
    assert df.loc["2222222", MF.grade] == 0 and pd.isna(df.loc["2222222", "Q1"])
    assert df.loc["5555555", MF.grade] == 12.0
    assert df.loc["5555555", MF.mdate] == "lundi 01 septembre 2026, 10:00"
    # the copy whose matricule is not in the roster adds no row
    assert "4444444" not in df.index


def test_finalized_job_is_archived_with_its_outputs_recorded(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    fake_pdflatex: list[str],
) -> None:
    job = _job(mongo_db, storage_root)
    _split_copies(tmp_path, mongo_db, scanned_copy_factory)

    sio = _finalize(job, tmp_path)

    assert _statuses(sio) == ["FINALIZING", "ARCHIVED"]
    record = mongo_db["eval_jobs"].find_one({"job_id": "job"})
    assert record["job_status"] == "ARCHIVED"
    assert record["notes_file_id"] == "output_csv/job.csv"
    output = mongo_db["jobs_output"].find_one({"job_id": "job"})
    assert output["stats_file_id"] == "output_stats/job.pdf"
    assert output["zip_id_list"] == ["output_zip/job_all.zip", "output_zip/job_1.zip"]
    for file_id in output["zip_id_list"] + [
        output["stats_file_id"],
        output["notes_csv_file_id"],
    ]:
        assert (storage_root / file_id).is_file(), file_id
    for name in ("alice", "carol", "dave"):
        assert (
            mongo_db["job_documents"].find_one({"filename": name})["status"]
            == "VALIDATED"
        )


def test_all_copies_zip_holds_the_merged_copies_gathered_by_group(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    fake_pdflatex: list[str],
) -> None:
    job = _job(mongo_db, storage_root)
    _split_copies(tmp_path, mongo_db, scanned_copy_factory)

    _finalize(job, tmp_path)

    all_zip = storage_root / "output_zip" / "job_all.zip"
    # no deleted copy, no copy outside the roster
    assert _zip_names(all_zip) == {
        "A/Martin_Alice_1111111.pdf",
        "B/Tremblay_Carol_3333333.pdf",
    }
    # cover page + the four pages of the non-ignored questions
    alice = _read_zip(all_zip, "A/Martin_Alice_1111111.pdf")
    work = tmp_path / "alice.pdf"
    work.write_bytes(alice)
    assert len(PdfReader(str(work)).pages) == 5


def test_the_grades_are_written_on_the_cover_page_and_read_back(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    fake_pdflatex: list[str],
) -> None:
    from process_copy import recognize
    from process_copy.classifier import load_classifier
    from process_copy.pages import gray_images

    job = _job(mongo_db, storage_root)
    _split_copies(tmp_path, mongo_db, scanned_copy_factory, {"alice": COPIES["alice"]})

    _finalize(job, tmp_path)

    work = tmp_path / "alice.pdf"
    work.write_bytes(
        _read_zip(
            storage_root / "output_zip" / "job_all.zip", "A/Martin_Alice_1111111.pdf"
        )
    )
    cover = gray_images(str(work), [0], straighten=False)[0]
    classifier = load_classifier(str(EXECUTOR / "digit_recognizer.tflite"))
    matched, numbers, *_ = recognize.grade(
        cover, GRADE_BOX, classifier=classifier, max_grade=30, max_question=12
    )
    # the ignored Q2 box is left blank (read as 0); the total includes the bonus
    assert matched
    assert numbers == [3, 0, 2.5, 1, 1.5, 8]
    # the original cover page is kept to write the grades again on a rerun
    assert (storage_root / "cover_pages" / "job" / "alice_cover_nograde.pdf").is_file()


def test_moodle_zip_has_one_folder_per_student_with_copy_and_stats(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    fake_pdflatex: list[str],
) -> None:
    job = _job(mongo_db, storage_root)
    _split_copies(tmp_path, mongo_db, scanned_copy_factory)

    _finalize(job, tmp_path)

    moodle_zip = storage_root / "output_zip" / "job_1.zip"
    alice_folder = ALICE_MOODLE_FOLDER
    carol_folder = "Tremblay Carol_103_3333333_assignsubmission_file_/"
    assert _zip_names(moodle_zip) == {
        alice_folder + "Martin_Alice_1111111.pdf",
        alice_folder + "Martin_Alice_1111111_notes.pdf",
        carol_folder + "Tremblay_Carol_3333333.pdf",
        carol_folder + "Tremblay_Carol_3333333_notes.pdf",
    }
    notes = _read_zip(
        moodle_zip, alice_folder + "Martin_Alice_1111111_notes.pdf"
    ).decode()
    assert "\\renewcommand{\\nom}{Martin Alice}" in notes
    lines = [line.split(" & ")[:3] for line in notes.splitlines()[2:]]
    # question label (/ max points), the student's grade, the class average
    assert lines == [
        ["1 (/ 5)", "3.0", "3.50"],
        ["3 (/ 5)", "2.5", "1.25"],
        ["4 (/ 5)", "1.0", "1.50"],
        ["5 (/ 2)", "1.5", "0.75"],
        ["Total (/ 15)", "8.0", "7.00"],  # the bonus is not in the maximum
    ]
    carol = _read_zip(
        moodle_zip, carol_folder + "Tremblay_Carol_3333333_notes.pdf"
    ).decode()
    assert "\\renewcommand{\\nom}{Tremblay Carol}" in carol
    assert "Total (/ 15) & 6.0 & 7.00" in carol


def test_teacher_stats_have_the_averages_and_no_student_column(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    fake_pdflatex: list[str],
) -> None:
    job = _job(mongo_db, storage_root)
    _split_copies(tmp_path, mongo_db, scanned_copy_factory)

    _finalize(job, tmp_path)

    teacher = (storage_root / "output_stats" / "job.pdf").read_text()
    assert "\\renewcommand{\\nom}{Statistiques}" in teacher
    assert "1 (/ 5) &  & 3.50 &" in teacher
    assert "Total (/ 15) &  & 7.00 &" in teacher
    # the boxplots are referenced from the compile folder, never through ".."
    assert "{Q1.png}" in teacher and "{Q5.png}" in teacher and "{Total.png}" in teacher
    assert "../" not in teacher
    assert "{Q2.png}" not in teacher


def test_without_moodle_structure_nor_student_stats_only_the_flat_zip_is_made(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    fake_pdflatex: list[str],
) -> None:
    roster = ROSTER.drop(columns=["Groupe"])
    job = _job(mongo_db, storage_root, moodle=False, student_stats=False, roster=roster)
    _split_copies(tmp_path, mongo_db, scanned_copy_factory, {"alice": COPIES["alice"]})

    _finalize(job, tmp_path)

    output = mongo_db["jobs_output"].find_one({"job_id": "job"})
    assert output["zip_id_list"] == ["output_zip/job_all.zip"]
    assert _zip_names(storage_root / "output_zip" / "job_all.zip") == {
        "Martin_Alice_1111111.pdf"
    }
    assert len(fake_pdflatex) == 1  # the teacher's stats only


def test_csv_values_cannot_escape_the_zip_or_run_as_formulas(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    fake_pdflatex: list[str],
) -> None:
    roster = ROSTER.copy()
    roster.loc[0, MF.name] = "../../evil"
    roster.loc[0, "Groupe"] = ".."
    roster.loc[2, MF.name] = '=HYPERLINK("http://x")'
    job = _job(mongo_db, storage_root, roster=roster)
    _split_copies(
        tmp_path,
        mongo_db,
        scanned_copy_factory,
        {"alice": COPIES["alice"], "carol": COPIES["carol"]},
    )

    _finalize(job, tmp_path)

    names = _zip_names(storage_root / "output_zip" / "job_all.zip") | _zip_names(
        storage_root / "output_zip" / "job_1.zip"
    )
    assert all(".." not in n.split("/") for n in names), names
    assert "_/.._.._evil__1111111.pdf" in names  # the ".." group becomes "_"
    assert not (storage_root.parent / "evil__1111111.pdf").exists()
    df = _grades_csv(storage_root)
    assert df.loc["3333333", MF.name] == '\'=HYPERLINK("http://x")'


def test_a_moodle_id_without_digits_leaves_the_copy_out_of_the_moodle_zip_only(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    fake_pdflatex: list[str],
) -> None:
    roster = ROSTER.copy()
    roster.loc[0, MF.id] = "Participant"
    job = _job(mongo_db, storage_root, roster=roster)
    _split_copies(
        tmp_path,
        mongo_db,
        scanned_copy_factory,
        {"alice": COPIES["alice"], "carol": COPIES["carol"]},
    )

    _finalize(job, tmp_path)

    assert "A/Martin_Alice_1111111.pdf" in _zip_names(
        storage_root / "output_zip" / "job_all.zip"
    )
    moodle = _zip_names(storage_root / "output_zip" / "job_1.zip")
    assert moodle and all(n.startswith("Tremblay Carol_103_3333333") for n in moodle)


def test_a_failing_student_stats_page_does_not_hold_back_the_copy(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    fake_pdflatex: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = finalize.create_stats_latex

    def failing_for_alice(nom: str, *args: Any, **kwargs: Any) -> Path:
        if nom == "Martin Alice":
            raise ChildProcessError("pdflatex failed")
        return real(nom, *args, **kwargs)

    monkeypatch.setattr(finalize, "create_stats_latex", failing_for_alice)
    job = _job(mongo_db, storage_root)
    _split_copies(
        tmp_path,
        mongo_db,
        scanned_copy_factory,
        {"alice": COPIES["alice"], "carol": COPIES["carol"]},
    )

    _finalize(job, tmp_path)

    moodle = _zip_names(storage_root / "output_zip" / "job_1.zip")
    assert (
        "Martin Alice_101_1111111_assignsubmission_file_/Martin_Alice_1111111.pdf"
        in moodle
    )
    assert not any(n.endswith("1111111_notes.pdf") for n in moodle)
    assert any(n.endswith("3333333_notes.pdf") for n in moodle)
    assert mongo_db["eval_jobs"].find_one({"job_id": "job"})["job_status"] == "ARCHIVED"


def test_the_moodle_zip_is_split_in_batches(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    fake_pdflatex: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(finalize, "BATCH_SIZE", 1e-9)  # a new archive after every file
    job = _job(mongo_db, storage_root, student_stats=False)
    _split_copies(
        tmp_path,
        mongo_db,
        scanned_copy_factory,
        {"alice": COPIES["alice"], "carol": COPIES["carol"]},
    )

    _finalize(job, tmp_path)

    zips = mongo_db["jobs_output"].find_one({"job_id": "job"})["zip_id_list"]
    assert zips == [
        "output_zip/job_all.zip",
        "output_zip/job_1.zip",
        "output_zip/job_2.zip",
    ]
    members = [_zip_names(storage_root / z) for z in zips[1:]]
    assert all(len(m) == 1 for m in members)


# --------------------------------------------------------- other job shapes


def test_a_matricule_only_job_ships_the_original_copies(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    pdf_factory: Callable[..., Path],
    fake_pdflatex: list[str],
) -> None:
    job = _job(mongo_db, storage_root, points=[], pages=[], bonus=[])
    pdf_factory(storage_root / "documents" / "job" / "all" / "alice.pdf", 3)
    mongo_db["job_documents"].insert_one(
        {
            "job_id": "job",
            "document_index": 0,
            "filename": "alice",
            "matricule": "1111111",
            "grades": [],
            "status": "HIGH_ACCURACY",
        }
    )

    _finalize(job, tmp_path)

    df = _grades_csv(storage_root)
    assert not [c for c in df.columns if c.startswith("Q")]
    assert df.loc["1111111", MF.grade] == 0
    all_zip = storage_root / "output_zip" / "job_all.zip"
    assert _zip_names(all_zip) == {"A/Martin_Alice_1111111.pdf"}
    # the original stays in documents: it was copied, not moved
    assert (storage_root / "documents" / "job" / "all" / "alice.pdf").is_file()
    assert (
        mongo_db["job_documents"].find_one({"filename": "alice"})["status"]
        == "VALIDATED"
    )
    assert mongo_db["eval_jobs"].find_one({"job_id": "job"})["job_status"] == "ARCHIVED"


def test_a_matricule_only_job_without_any_copy_still_archives(
    tmp_path: Path, storage_root: Path, mongo_db: Any, fake_pdflatex: list[str]
) -> None:
    job = _job(mongo_db, storage_root, points=[], pages=[], bonus=[])

    _finalize(job, tmp_path)

    output = mongo_db["jobs_output"].find_one({"job_id": "job"})
    # an empty moodle archive is not kept
    assert output["zip_id_list"] == ["output_zip/job_all.zip"]
    assert _zip_names(storage_root / "output_zip" / "job_all.zip") == set()
    assert mongo_db["eval_jobs"].find_one({"job_id": "job"})["job_status"] == "ARCHIVED"


def test_a_rerun_after_the_merge_zips_the_merged_copies_as_they_are(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    pdf_factory: Callable[..., Path],
    fake_pdflatex: list[str],
) -> None:
    # documents/<job> is gone (cleaned after an earlier merge): the copies in
    # corrected_copies are zipped without writing on them again
    job = _job(mongo_db, storage_root)
    job["job_status"] = "FINALIZING"
    merged = pdf_factory(storage_root / "corrected_copies" / "job" / "alice.pdf", 5)
    content = merged.read_bytes()
    mongo_db["job_documents"].insert_one(
        {
            "job_id": "job",
            "document_index": 0,
            "filename": "alice",
            "matricule": "1111111",
            "grades": [3, None, 2.5, 1, 1.5],
            "status": "VALIDATED",
        }
    )

    sio = _finalize(job, tmp_path)

    assert _statuses(sio) == ["ARCHIVED"]  # already FINALIZING: not announced again
    assert (
        _read_zip(
            storage_root / "output_zip" / "job_all.zip", "A/Martin_Alice_1111111.pdf"
        )
        == content
    )
    assert _grades_csv(storage_root).loc["1111111", MF.grade] == 8.0


def test_a_deleted_copy_stays_deleted_when_the_job_is_finalized_again(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    fake_pdflatex: list[str],
) -> None:
    # a duplicate scan of Alice, deleted at validation: finalized a second
    # time (the server lets a job in ERROR be validated again), it must not
    # come back and overwrite Alice's copy and grades with its empty ones
    job = _job(mongo_db, storage_root)
    copies = {
        "alice": COPIES["alice"],
        "alice_again": ("1111111", [None] * 5, "DELETED"),
        "carol": COPIES["carol"],
    }
    _split_copies(tmp_path, mongo_db, scanned_copy_factory, copies)

    _finalize(job, tmp_path)
    # the executor works in a fresh folder for every job it runs
    shutil.rmtree(tmp_path / "work")
    _finalize(job, tmp_path)

    status = mongo_db["job_documents"].find_one({"filename": "alice_again"})["status"]
    assert status == "DELETED"
    assert _grades_csv(storage_root).loc["1111111", MF.grade] == 8.0
    assert not (storage_root / "corrected_copies" / "job" / "alice_again.pdf").exists()
    all_zip = storage_root / "output_zip" / "job_all.zip"
    assert _zip_names(all_zip) == {
        "A/Martin_Alice_1111111.pdf",
        "B/Tremblay_Carol_3333333.pdf",
    }
    notes = _read_zip(
        storage_root / "output_zip" / "job_1.zip",
        ALICE_MOODLE_FOLDER + "Martin_Alice_1111111_notes.pdf",
    ).decode()
    assert "Total (/ 15) & 8.0 & 7.00" in notes


# --------------------------------------------------- stops and failures


class _StopAfter:
    """A stop handler that says "deleted" from its n-th call on."""

    def __init__(self, n: int) -> None:
        self.calls = 0
        self.n = n

    def stop(self) -> bool:
        """Whether the job counts as deleted at this call."""
        self.calls += 1
        return self.calls >= self.n


def test_a_job_deleted_before_the_zips_is_cleaned_up(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    pdf_factory: Callable[..., Path],
    fake_pdflatex: list[str],
) -> None:
    job = _job(mongo_db, storage_root, points=[], pages=[], bonus=[])
    pdf_factory(storage_root / "documents" / "job" / "all" / "alice.pdf", 3)
    mongo_db["job_documents"].insert_one(
        {
            "job_id": "job",
            "document_index": 0,
            "filename": "alice",
            "matricule": "1111111",
            "grades": [],
            "status": "VALIDATED",
        }
    )

    sio = _finalize(job, tmp_path, stop=_StopAfter(1))

    assert _statuses(sio) == ["FINALIZING"]
    assert not (storage_root / "output_zip").exists()
    assert not (storage_root / "corrected_copies" / "job").exists()
    assert not (storage_root / "documents" / "job").exists()
    assert not (storage_root / "output_csv" / "job.csv").exists()
    assert mongo_db["job_documents"].count_documents({"job_id": "job"}) == 0
    assert mongo_db["jobs_output"].count_documents({"job_id": "job"}) == 0


def test_a_job_deleted_while_zipping_loses_the_zips_and_stats_made(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    pdf_factory: Callable[..., Path],
    fake_pdflatex: list[str],
) -> None:
    job = _job(mongo_db, storage_root, points=[], pages=[], bonus=[])
    pdf_factory(storage_root / "documents" / "job" / "all" / "alice.pdf", 3)
    mongo_db["job_documents"].insert_one(
        {
            "job_id": "job",
            "document_index": 0,
            "filename": "alice",
            "matricule": "1111111",
            "grades": [],
            "status": "VALIDATED",
        }
    )

    sio = _finalize(job, tmp_path, stop=_StopAfter(2))

    assert "ARCHIVED" not in _statuses(sio)
    assert list((storage_root / "output_zip").iterdir()) == []
    assert not (storage_root / "output_stats" / "job.pdf").exists()
    assert mongo_db["jobs_output"].count_documents({"job_id": "job"}) == 0


def test_a_failed_move_to_storage_sets_the_job_in_error(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    fake_pdflatex: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _job(mongo_db, storage_root, points=[], pages=[], bonus=[])
    real_move = Storage.move_to

    def move_to(self, src: str, dest: str) -> Any:
        if dest.startswith("output_csv"):
            raise OSError("NFS unavailable")
        return real_move(self, src, dest)

    monkeypatch.setattr(Storage, "move_to", move_to)

    _finalize(job, tmp_path)

    record = mongo_db["eval_jobs"].find_one({"job_id": "job"})
    assert record["job_status"] == "ERROR"
    assert record["job_infos"] == "NFS unavailable"


def test_dispatch_reports_a_job_without_output_csv_as_an_error(
    tmp_path: Path, storage_root: Path, mongo_db: Any, fake_pdflatex: list[str]
) -> None:
    _job(mongo_db, storage_root, points=[], pages=[], bonus=[])
    mongo_db["jobs_output"].delete_many({})
    sio = MagicMock()

    dispatch.process(
        Database(), MagicMock(), Storage(), sio, {"job_id": "job"}, tmp_path
    )

    record = mongo_db["eval_jobs"].find_one({"job_id": "job"})
    assert record["job_status"] == "ERROR"
    assert record["job_infos"].startswith("Échec de la finalisation")
    assert "no output csv" in record["job_infos"]
    assert _statuses(sio) == ["FINALIZING", "ERROR"]


def test_dispatch_reports_a_failing_pdflatex_as_an_error(
    tmp_path: Path, storage_root: Path, mongo_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(
        latex_file: str | Path,
        tmp_dir: str | Path,
        latex_cmd: str = "pdflatex",
        timeout: float | None = 5,
    ) -> str:
        raise ChildProcessError("pdflatex failed with exit code 1 (log above).")

    monkeypatch.setattr(stats, "create_tex_pdf", broken)
    _job(mongo_db, storage_root, points=[], pages=[], bonus=[])

    dispatch.process(
        Database(), MagicMock(), Storage(), MagicMock(), {"job_id": "job"}, tmp_path
    )

    record = mongo_db["eval_jobs"].find_one({"job_id": "job"})
    assert record["job_status"] == "ERROR"
    assert "pdflatex failed with exit code 1" in record["job_infos"]


def _pdflatex_runs() -> bool:
    try:
        return (
            subprocess.run(
                ["pdflatex", "-version"], capture_output=True, timeout=20
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _pdflatex_runs(), reason="no working pdflatex")
def test_finalize_compiles_real_stats_pdfs(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the LaTeX sources are found relative to the working directory, as in
    # the container (WORKDIR is the executor root)
    monkeypatch.chdir(EXECUTOR)
    job = _job(mongo_db, storage_root)
    _split_copies(
        tmp_path,
        mongo_db,
        scanned_copy_factory,
        {"alice": COPIES["alice"], "carol": COPIES["carol"]},
    )

    _finalize(job, tmp_path)

    assert (storage_root / "output_stats" / "job.pdf").read_bytes().startswith(b"%PDF")
    notes = _read_zip(
        storage_root / "output_zip" / "job_1.zip",
        ALICE_MOODLE_FOLDER + "Martin_Alice_1111111_notes.pdf",
    )
    assert notes.startswith(b"%PDF")
    assert mongo_db["eval_jobs"].find_one({"job_id": "job"})["job_status"] == "ARCHIVED"
