"""The recognition command line (``parse_run_args``) outside the job pipeline.

The executor only runs ``-f`` (find the matricules, see test_process_job);
these are the other modes of the tool a teacher runs by hand: ``-g`` reads
the grades printed in the cover-page table, ``-e`` exports copies to the
Moodle feedback structure and ``-i`` imports them back. The grade reading
uses the real cover-page scans of ``fixtures/recognition``.
"""

import json
import os
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

import process_copy.batch as batch
import process_copy.grades as grades
import process_copy.matricules as matricules
from process_copy import mcc
from process_copy.parser import parse_run_args
from rmn_common.moodle import MoodleFields as MF

SPEC = json.loads(
    (
        Path(__file__).resolve().parent / "fixtures" / "recognition" / "expected.json"
    ).read_text()
)
GRADE_BOX = SPEC["grade_box"]


class InlineProcess:
    """``multiprocessing.Process`` run in the calling process.

    A real child process would not see the in-memory MongoDB.
    """

    def __init__(self, target: Callable[..., Any], args: Any) -> None:
        self._target, self._args, self.exitcode = target, args, None

    def start(self) -> None:
        """Run the target to completion, as a worker that exits normally."""
        self._target(*self._args)
        self.exitcode = 0

    def join(self, timeout: float | None = None) -> None:
        """Nothing to wait for: the target already ran in ``start``."""


@pytest.fixture
def inline_workers(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Run the recognition workers inline; return the socket they emit on."""
    sio = MagicMock()
    monkeypatch.setattr(batch, "Process", InlineProcess)
    for module in (batch, grades, matricules):
        monkeypatch.setattr(module, "socketio_client", lambda: sio)
    return sio


def _roster(path: Path, rows: list[list]) -> Path:
    df = pd.DataFrame(
        rows, columns=[MF.id, MF.name, MF.mat, MF.grade, MF.max, MF.mdate]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


# ------------------------------------------------------------------- -g


@pytest.fixture
def grade_mode(
    tmp_path: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    inline_workers: MagicMock,
) -> Callable[..., tuple]:
    """Run ``-g exam`` on copies whose cover page shows ``covers`` ({file: crop});
    return the documents recorded, by file name, and the roster csv."""

    def run(
        covers: dict[str, str],
        roster: list[list],
        retry: int = 0,
        validate_matricule: bool = True,
    ) -> tuple[dict, Path]:
        copies = tmp_path / "all"
        for name, crop in covers.items():
            scanned_copy_factory(copies / name, [(crop, GRADE_BOX)])
        csv = _roster(tmp_path / "notes.csv", roster)
        mongo_db["eval_jobs"].insert_one(
            {
                "job_id": "job",
                "user_id": "u",
                "retry": retry,
                "validate_matricule": validate_matricule,
            }
        )
        parse_run_args(
            [
                str(copies),
                "-g",
                "exam",
                "--grades",
                str(csv),
                "--job_id",
                "job",
                "--user_id",
                "u",
                "-m",
                str(tmp_path / "moodle"),
            ]
        )
        docs = {
            d["filename"]: d for d in mongo_db["job_documents"].find({"job_id": "job"})
        }
        return docs, csv

    return run


ROSTER = [
    ["Participant 1", "Martin Alice", 2478756, None, 30, "-"],
    ["Participant 2", "Roy Bob", 2448628, None, 30, "-"],
]


def test_grade_mode_reads_the_cover_tables_into_the_database(
    grade_mode: Callable[..., tuple], mongo_db: Any, inline_workers: MagicMock
) -> None:
    docs, _ = grade_mode(
        {
            "copie_2478756.pdf": "grades_printed_ones.png",
            "copie_2448628.pdf": "grades_printed_with_zero.png",
        },
        ROSTER,
    )

    assert docs["copie_2478756.pdf"]["grades"] == [1, 1, 1, 1, 1]
    assert docs["copie_2448628.pdf"]["grades"] == [0, 1, 1, 1, 1]
    assert docs["copie_2478756.pdf"]["status"] == "HIGH ACCURACY"
    assert docs["copie_2478756.pdf"]["matricule"] == "2478756"
    # learned from the copies: every later copy is fixed to five questions
    assert mongo_db["eval_jobs"].find_one({"job_id": "job"})["max_questions"] == 5
    ready = [
        json.loads(c.args[1])
        for c in inline_workers.emit.call_args_list
        if c.args[0] == "document_ready"
    ]
    assert {r["document_index"] for r in ready} == {0, 1}


@pytest.mark.xfail(
    strict=True,
    reason="batch.process_all rewrites the csv with the dataframes it loaded "
    "before the "
    "workers ran, so the grades grade_files wrote to the csv are lost",
)
def test_grade_mode_writes_the_grades_read_in_the_csv(
    grade_mode: Callable[..., tuple],
) -> None:
    _, csv = grade_mode({"copie_2478756.pdf": "grades_printed_ones.png"}, ROSTER)

    df = pd.read_csv(csv, index_col=MF.mat)
    assert df.loc[2478756, [f"{MF.question} {i}" for i in range(1, 6)]].tolist() == [
        1,
        1,
        1,
        1,
        1,
    ]
    assert df.loc[2478756, MF.grade] == 5


def test_grade_mode_flags_a_copy_of_an_unknown_student(
    grade_mode: Callable[..., tuple],
) -> None:
    docs, csv = grade_mode(
        {"copie_2999999.pdf": "grades_printed_ones.png"},
        ROSTER,
        retry=1,
        validate_matricule=False,
    )

    # the grades read are kept in the database only
    assert docs["copie_2999999.pdf"]["grades"] == [1, 1, 1, 1, 1]
    assert docs["copie_2999999.pdf"]["group"] == ""
    assert list(pd.read_csv(csv, index_col=MF.mat).index) == [2478756, 2448628]


def test_a_blank_cover_table_reads_as_zeros(
    grade_mode: Callable[..., tuple], mongo_db: Any, inline_workers: MagicMock
) -> None:
    docs, _ = grade_mode(
        {"copie_2478756.pdf": "grades_blank.png"}, ROSTER, validate_matricule=False
    )

    # an empty box reads as 0, and the zero total checks out
    assert docs["copie_2478756.pdf"]["grades"] == [0, 0, 0, 0, 0]
    assert docs["copie_2478756.pdf"]["status"] == "VALIDATED"


# ------------------------------------------------------------ -e and -i


def test_export_builds_the_moodle_folders_and_zips_them(
    tmp_path: Path, pdf_factory: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    copies = tmp_path / "all"
    pdf_factory(copies / "Martin_2478756.pdf")
    pdf_factory(copies / "Roy_2448628.pdf")
    pdf_factory(copies / "sans_matricule.pdf")
    csv = _roster(
        tmp_path / "notes.csv",
        [
            ["Participant 1", "Martin Alice", 2478756, None, 30, "-"],
            ["Participant 2", "Roy Bob", 2448628, None, 30, "-"],
        ],
    )
    moodle = tmp_path / "moodle"
    monkeypatch.chdir(tmp_path)

    parse_run_args([str(copies), "-e", "-m", str(moodle), "--grades", str(csv)])

    with zipfile.ZipFile(tmp_path / "moodle.zip") as z:
        names = set(z.namelist())
    assert names == {
        "Martin Alice_1_2478756_assignsubmission_file_/Martin_2478756.pdf",
        "Roy Bob_2_2448628_assignsubmission_file_/Roy_2448628.pdf",
        "sans_matricule.pdf",  # copied as is when no matricule is found
    }
    # the files are moved into the archive
    assert not any(p.is_file() for p in moodle.rglob("*"))


def test_import_renames_the_moodle_submissions(
    tmp_path: Path, pdf_factory: Callable[..., Path]
) -> None:
    moodle = tmp_path / "moodle"
    pdf_factory(moodle / "Martin Alice_1_2478756_assignsubmission_file_" / "devoir.pdf")
    pdf_factory(moodle / "Roy Bob_2_2448628_assignsubmission_file_" / "remise.pdf")
    (moodle / "index.html").write_text("ignored")
    out = tmp_path / "all"

    parse_run_args(
        [
            str(out),
            "-i",
            "-m",
            str(moodle),
            "-co",
            "MTH1102",
            "-se",
            "H22",
            "-na",
            "Intra",
        ]
    )

    assert sorted(os.listdir(out)) == [
        "Martin_Alice_2478756_MTH1102_H22_Intra.pdf",
        "Roy_Bob_2448628_MTH1102_H22_Intra.pdf",
    ]


def test_import_refuses_a_submission_with_several_files(
    tmp_path: Path, pdf_factory: Callable[..., Path]
) -> None:
    moodle = tmp_path / "moodle"
    folder = moodle / "Martin Alice_1_2478756_assignsubmission_file_"
    pdf_factory(folder / "a.pdf")
    pdf_factory(folder / "b.pdf")

    with pytest.raises(ValueError, match="does not contain only one file"):
        mcc.import_files([str(tmp_path / "all")], str(moodle))


def test_import_with_the_matricules_csv_sorts_the_copies_by_roster(
    tmp_path: Path, pdf_factory: Callable[..., Path]
) -> None:
    first = pdf_factory(tmp_path / "scan1.pdf")
    second = pdf_factory(tmp_path / "scan2.pdf")
    group_a = _roster(
        tmp_path / "grA.csv",
        [["Participant 1", "Martin Alice", "2478756", None, 30, "-"]],
    )
    group_b = _roster(
        tmp_path / "grB.csv", [["Participant 2", "Roy Bob", "2448628", None, 30, "-"]]
    )
    matricules_csv = tmp_path / "matricules.csv"
    matricules_csv.write_text(
        "Id,Matricule,NomComplet,File\n"
        f"1,2478756,,{first}\n2,2448628,,{second}\n3,,,x.pdf\n"
    )
    out = tmp_path / "all"

    mcc.import_files_with_csv(
        [str(out)], str(matricules_csv), [str(group_a), str(group_b)], suffix="Intra"
    )

    assert os.listdir(out / "grA") == ["Martin Alice_2478756_Intra.pdf"]
    assert os.listdir(out / "grB") == ["Roy Bob_2448628_Intra.pdf"]


def test_import_with_the_matricules_csv_refuses_an_unknown_or_repeated_matricule(
    tmp_path: Path, pdf_factory: Callable[..., Path]
) -> None:
    roster = _roster(
        tmp_path / "notes.csv",
        [["Participant 1", "Martin Alice", "2478756", None, 30, "-"]],
    )
    unknown = tmp_path / "unknown.csv"
    unknown.write_text("Id,Matricule,NomComplet,File\n1,2999999,,a.pdf\n")
    repeated = tmp_path / "repeated.csv"
    repeated.write_text(
        "Id,Matricule,NomComplet,File\n1,2478756,,a.pdf\n2,2478756,,b.pdf\n"
    )

    with pytest.raises(ValueError, match="not found in any csv"):
        mcc.import_files_with_csv([str(tmp_path / "all")], str(unknown), [str(roster)])
    with pytest.raises(ValueError, match="more than once"):
        mcc.import_files_with_csv([str(tmp_path / "all")], str(repeated), [str(roster)])


def test_duplicated_students_are_dropped_from_the_roster(tmp_path: Path) -> None:
    csv = _roster(
        tmp_path / "notes.csv",
        [
            ["Participant 1", "Martin Alice", 2478756, None, 30, "-"],
            ["Participant 9", "Martin Alice", 2478756, None, 30, "-"],
        ],
    )
    dfs, names = mcc.load_csv([str(csv)])
    assert names == ["notes"]
    assert list(dfs[0].index) == ["2478756"]
    assert dfs[0].loc["2478756", MF.id] == "Participant 1"


def test_copy_file_renames_or_keeps_the_name(
    tmp_path: Path, pdf_factory: Callable[..., Path]
) -> None:
    src = pdf_factory(tmp_path / "src.pdf")
    mcc.copy_file(str(src), str(tmp_path / "out" / "renamed.pdf"))
    mcc.copy_file(str(src), str(tmp_path / "folder"))
    assert (tmp_path / "out" / "renamed.pdf").is_file()
    assert (tmp_path / "folder" / "src.pdf").is_file()
