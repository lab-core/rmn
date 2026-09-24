"""Reading the matricules of a new job (process_job), end to end.

``process_job`` runs the recognition CLI (``parse_run_args``), which reads
every cover page in worker processes. The worker is run inline here
(``InlineProcess``): a real child process would not see the in-memory
MongoDB. Everything else is real, down to the handwritten matricules of
``fixtures/recognition`` pasted on the cover pages and the digit model.
"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

import process_copy.batch as batch
import process_copy.matricules as matricules
import runtime
from process_copy.database import Database
from rmn_common.moodle import MoodleFields as MF
from rmn_common.status import Document_Status
from tasks.process import process_job
from utils.split import split_and_save
from utils.stop_handler import StopHandler
from utils.storage import Storage

SPEC = json.loads(
    (
        Path(__file__).resolve().parent / "fixtures" / "recognition" / "expected.json"
    ).read_text()
)
MATRICULE_BOX = SPEC["matricule_box"]
PAGES = {"Q1": 1}
HIGH_ACCURACY = Document_Status.HIGH_ACCURACY.value
TO_VALIDATE = Document_Status.TO_VALIDATE.value
VALIDATED = Document_Status.VALIDATED.value
ROSTER = pd.DataFrame(
    {
        MF.id: ["Participant 1", "Participant 2", "Participant 3"],
        MF.name: ["Martin Alice", "Roy Bob", "Gagnon Eve"],
        MF.mat: ["2478756", "2448628", "1999999"],
        "Groupe": ["A", "B", "B"],
        MF.grade: [None, None, None],
        MF.status: ["Remis pour évaluation", "Remis pour évaluation", "Aucune remise"],
    }
)


class InlineProcess:
    """``multiprocessing.Process`` that runs its target in the calling process."""

    def __init__(self, target: Callable[..., Any], args: Any) -> None:
        self._target = target
        self._args = args
        self.exitcode = None

    def start(self) -> None:
        """Run the target to completion, as a worker that exits normally."""
        self._target(*self._args)
        self.exitcode = 0

    def join(self, timeout: float | None = None) -> None:
        """Nothing to wait for: the target already ran in ``start``."""


@pytest.fixture
def recognition(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    """Run the recognition workers inline; return the socket they emit on."""
    sio = MagicMock()
    monkeypatch.setattr(batch, "Process", InlineProcess)
    monkeypatch.setattr(batch, "socketio_client", lambda: sio)
    monkeypatch.setattr(matricules, "socketio_client", lambda: sio)
    yield sio
    runtime.apply_template_boxes(None, None, None)


def _new_job(
    mongo_db: Any, storage_root: Path, retry: int = 0, validate_matricule: bool = True
) -> dict:
    roster = storage_root / "notes" / "job.csv"
    roster.parent.mkdir(parents=True, exist_ok=True)
    ROSTER.to_csv(roster, index=False)
    job = {
        "job_id": "job",
        "user_id": "teacher",
        "job_status": "QUEUED",
        "notes_file_id": "notes/job.csv",
        "front_template_id": "front",
        "regular_template_id": None,
        "validate_matricule": validate_matricule,
        "retry": retry,
        "n_pages_per_question": [["Q1", 1]],
    }
    mongo_db["eval_jobs"].insert_one(dict(job))
    mongo_db["template"].insert_one(
        {"template_id": "front", "matricule_box": MATRICULE_BOX}
    )
    return job


def _upload(
    tmp_path: Path, scanned_copy_factory: Callable[..., Path], copies: dict
) -> None:
    """Split the copies ({name: matricule crop or None}) into the job's storage."""
    paths = []
    for name, crop in copies.items():
        crops = [(crop, MATRICULE_BOX)] if crop else []
        paths.append(
            str(scanned_copy_factory(tmp_path / "upload" / f"{name}.pdf", crops, 1))
        )
    _, errors = split_and_save(PAGES, paths, "job")
    assert errors == []


def _run(job: dict, tmp_path: Path, stop: Any = None) -> MagicMock:
    sio = MagicMock()
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    db = Database()
    process_job(
        db,
        Storage(),
        sio,
        job,
        work,
        stop or StopHandler(db.eval_jobs_collection(), "job"),
    )
    return sio


def _docs(mongo_db: Any) -> dict:
    return {d["filename"]: d for d in mongo_db["job_documents"].find({"job_id": "job"})}


def test_matricules_are_found_and_the_job_waits_for_validation(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    recognition: MagicMock,
) -> None:
    job = _new_job(mongo_db, storage_root)
    _upload(
        tmp_path,
        scanned_copy_factory,
        {"copie_2478756": None, "copie_2448628": None, "blank": None},
    )

    sio = _run(job, tmp_path)

    docs = _docs(mongo_db)
    alice = docs["copie_2478756"]
    # a matricule in the file name is taken as is, without reading the page
    assert (alice["matricule"], alice["group"], alice["matricule_confidence"]) == (
        "2478756",
        "A",
        1.0,
    )
    assert alice["status"] == HIGH_ACCURACY
    assert (docs["copie_2448628"]["matricule"], docs["copie_2448628"]["group"]) == (
        "2448628",
        "B",
    )
    # nothing written on the cover page: the teacher has to enter it
    assert docs["blank"]["status"] == TO_VALIDATE
    assert docs["blank"]["matricule"] == "NA"
    assert docs["blank"]["matricule_confidence"] == 0.0

    record = mongo_db["eval_jobs"].find_one({"job_id": "job"})
    assert record["job_status"] == "VALIDATION"
    assert record["job_infos"] == "Validation matricule prête"
    assert record["groups"] == ["A", "B"]
    assert {s["matricule"] for s in record["students_list"]} == {
        "2478756",
        "2448628",
        "1999999",
    }
    statuses = [json.loads(c.args[1])["status"] for c in sio.emit.call_args_list]
    assert statuses == ["VALIDATION"]
    # each copy is announced to the validation screen as it is read
    ready = [
        json.loads(c.args[1])
        for c in recognition.emit.call_args_list
        if c.args[0] == "document_ready"
    ]
    assert sorted(r["document_index"] for r in ready) == [0, 1, 2]


def test_a_handwritten_matricule_is_read_from_the_cover_page(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    recognition: MagicMock,
) -> None:
    job = _new_job(mongo_db, storage_root)
    _upload(tmp_path, scanned_copy_factory, {"alice": "matricule_01.png"})

    _run(job, tmp_path)

    doc = _docs(mongo_db)["alice"]
    assert (doc["matricule"], doc["status"], doc["group"]) == (
        "2478756",
        HIGH_ACCURACY,
        "A",
    )


def test_the_roster_is_saved_as_the_job_output(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    recognition: MagicMock,
) -> None:
    job = _new_job(mongo_db, storage_root)
    _upload(tmp_path, scanned_copy_factory, {"copie_2478756": None})

    _run(job, tmp_path)

    output = mongo_db["jobs_output"].find_one({"job_id": "job"})
    assert output["notes_csv_file_id"] == "output_csv/job.csv"
    assert output["zip_id_list"] == [] and output["preview_file_id"] == "None"
    saved = pd.read_csv(storage_root / "output_csv" / "job.csv", dtype={MF.mat: str})
    # the copies handed in on Moodle come first, each part by matricule
    assert saved[MF.mat].tolist() == ["2448628", "2478756", "1999999"]


def test_without_matricule_validation_a_found_matricule_is_validated(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    recognition: MagicMock,
) -> None:
    job = _new_job(mongo_db, storage_root, validate_matricule=False)
    _upload(tmp_path, scanned_copy_factory, {"copie_2478756": None, "blank": None})

    _run(job, tmp_path)

    docs = _docs(mongo_db)
    assert docs["copie_2478756"]["status"] == VALIDATED
    assert docs["blank"]["status"] == TO_VALIDATE


def test_a_rerun_keeps_the_copies_already_read(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    recognition: MagicMock,
) -> None:
    job = _new_job(mongo_db, storage_root, retry=1)
    _upload(tmp_path, scanned_copy_factory, {"copie_2478756": None, "blank": None})
    # the teacher entered the blank copy's matricule before the job was requeued
    mongo_db["job_documents"].update_one(
        {"filename": "blank"}, {"$set": {"status": VALIDATED, "matricule": "1999999"}}
    )

    _run(job, tmp_path)

    docs = _docs(mongo_db)
    assert (docs["blank"]["status"], docs["blank"]["matricule"]) == (
        VALIDATED,
        "1999999",
    )
    assert docs["copie_2478756"]["matricule"] == "2478756"


def test_the_template_boxes_are_applied_for_the_job(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    recognition: MagicMock,
) -> None:
    job = _new_job(mongo_db, storage_root)
    mongo_db["template"].update_one(
        {"template_id": "front"},
        {
            "$set": {
                "matricule_box": [0.111, 0.2, 0.1, 0.2],
                "grade_box": [0.5, 0.6, 0.7, 0.8],
            }
        },
    )
    _upload(tmp_path, scanned_copy_factory, {"copie_2478756": None})

    _run(job, tmp_path)

    assert runtime.matricule_box["exam"]["front"] == (0.11, 0.2, 0.1, 0.2)
    assert runtime.grade_box["exam"]["grade"] == (0.5, 0.6, 0.7, 0.8)


def test_a_failing_recognition_is_retried_then_reported(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    recognition: MagicMock,
) -> None:
    job = _new_job(mongo_db, storage_root)
    ROSTER.drop(columns=[MF.mat]).to_csv(
        storage_root / "notes" / "job.csv", index=False
    )
    _upload(tmp_path, scanned_copy_factory, {"copie_2478756": None})

    with pytest.raises(KeyError):
        _run(job, tmp_path)
    record = mongo_db["eval_jobs"].find_one({"job_id": "job"})
    assert "Matricule" in record["job_infos"]
    assert record["job_status"] == "RUN"  # left for the idle sweep to requeue

    mongo_db["eval_jobs"].update_one(
        {"job_id": "job"}, {"$set": {"retry": runtime.MAX_RETRY}}
    )
    sio = _run(job, tmp_path)
    record = mongo_db["eval_jobs"].find_one({"job_id": "job"})
    assert record["job_status"] == "ERROR"
    assert json.loads(sio.emit.call_args.args[1])["status"] == "ERROR"
    assert mongo_db["jobs_output"].count_documents({"job_id": "job"}) == 0


def test_a_job_deleted_while_failing_is_cleaned_up_instead_of_retried(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    recognition: MagicMock,
) -> None:
    job = _new_job(mongo_db, storage_root)
    ROSTER.drop(columns=[MF.mat]).to_csv(
        storage_root / "notes" / "job.csv", index=False
    )
    _upload(tmp_path, scanned_copy_factory, {"copie_2478756": None})
    stop = MagicMock()
    stop.stop.return_value = True

    _run(job, tmp_path, stop=stop)  # does not raise: nothing left to retry

    assert mongo_db["job_documents"].count_documents({"job_id": "job"}) == 0
    assert not (storage_root / "documents" / "job").exists()


def test_a_worker_that_dies_stops_the_job_instead_of_looping(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    recognition: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DeadProcess(InlineProcess):
        """A worker killed before it reported anything."""

        def start(self) -> None:
            self.exitcode = -9  # killed before it reported anything

    monkeypatch.setattr(batch, "Process", DeadProcess)
    job = _new_job(mongo_db, storage_root, retry=runtime.MAX_RETRY)
    _upload(tmp_path, scanned_copy_factory, {"alice": None})

    _run(job, tmp_path)

    record = mongo_db["eval_jobs"].find_one({"job_id": "job"})
    assert record["job_status"] == "ERROR"
    assert "No progress at document 0" in record["job_infos"]


def test_a_job_deleted_during_recognition_is_cleaned_up(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    scanned_copy_factory: Callable[..., Path],
    recognition: MagicMock,
) -> None:
    job = _new_job(mongo_db, storage_root)
    _upload(tmp_path, scanned_copy_factory, {"copie_2478756": None})
    stop = MagicMock()
    stop.stop.return_value = True

    _run(job, tmp_path, stop=stop)

    assert mongo_db["job_documents"].count_documents({"job_id": "job"}) == 0
    assert mongo_db["jobs_output"].count_documents({"job_id": "job"}) == 0
    assert not (storage_root / "documents" / "job").exists()
    assert not (storage_root / "output_csv" / "job.csv").exists()


def test_a_job_that_vanished_is_not_processed(tmp_path: Path, mongo_db: Any) -> None:
    job = {"job_id": "job", "user_id": "teacher"}
    sio = _run(job, tmp_path)
    assert not sio.emit.called
    assert mongo_db["eval_jobs"].count_documents({}) == 0
