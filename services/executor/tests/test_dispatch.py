"""What a job from the queue turns into: dispatch by status, and the small tasks.

The routing tests replace the tasks by recorders (``routed``); the tasks that
are cheap to run for real -- adding copies from a zip, reading the grades of a
question, deleting a job, the queue loop of ``job_executor`` -- are run
against mongomock, fakeredis and the temporary storage.
"""

import json
import runpy
import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import fakeredis
import pytest

import tasks.cleanup as cleanup
import tasks.dispatch as dispatch
import tasks.templates as templates
import utils.clients as clients
from process_copy.database import Database
from rmn_common.status import Document_Status
from tasks.copies import add_copies_to_job
from tasks.process import create_job
from utils.storage import Storage

EXECUTOR = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
RECOGNITION = json.loads((FIXTURES / "recognition" / "expected.json").read_text())


def _statuses(sio: MagicMock) -> list[str]:
    return [
        json.loads(c.args[1])["status"]
        for c in sio.emit.call_args_list
        if c.args[0] == "job_status"
    ]


def _queue(redis: fakeredis.FakeStrictRedis) -> list[dict]:
    return [json.loads(p) for p in redis.lrange("job_queue", 0, -1)]


# ------------------------------------------------------------------ routing


@pytest.fixture
def routed(monkeypatch: pytest.MonkeyPatch) -> list:
    """Replace every task by a recorder; return the list of (task, args)."""
    calls = []
    for name in (
        "finalize_job",
        "read_grades_for_job",
        "add_copies_to_job",
        "process_job",
        "create_job",
    ):
        monkeypatch.setattr(
            dispatch, name, lambda *args, _name=name: calls.append((_name, args))
        )
    return calls


def _dispatch(mongo_db: Any, status: str, payload: dict | None = None) -> None:
    mongo_db["eval_jobs"].insert_one(
        {"job_id": "job", "user_id": "teacher", "job_status": status}
    )
    dispatch.process(
        Database(),
        MagicMock(),
        Storage(),
        MagicMock(),
        payload or {"job_id": "job"},
        Path("/tmp"),
    )


@pytest.mark.parametrize(
    "status, payload, task",
    [
        ("VALIDATED", {}, "finalize_job"),
        ("FINALIZING", {}, "finalize_job"),
        ("QUEUED", {}, "process_job"),
        ("IGNORED", {}, "process_job"),
        ("SPLIT", {}, "create_job"),
        ("CORRECTED", {}, "create_job"),
        (
            "VALIDATION",
            {"read_grades": True, "question_index": 2},
            "read_grades_for_job",
        ),
        ("RUN", {"read_grades": True, "question_index": 2}, "read_grades_for_job"),
        ("VALIDATION", {"add_copies": True}, "add_copies_to_job"),
        ("QUEUED", {"add_copies": True}, "add_copies_to_job"),
        # a finalization is never interrupted by a late request
        ("VALIDATED", {"read_grades": True, "question_index": 2}, "finalize_job"),
    ],
)
def test_the_job_status_and_payload_choose_the_task(
    mongo_db: Any, routed: list, status: str, payload: dict, task: str
) -> None:
    _dispatch(mongo_db, status, {"job_id": "job", **payload})
    assert [name for name, _ in routed] == [task]


def test_read_grades_is_given_the_question_and_run_of_the_payload(
    mongo_db: Any, routed: list
) -> None:
    _dispatch(
        mongo_db,
        "VALIDATION",
        {"job_id": "job", "read_grades": True, "question_index": 4, "run": 7},
    )
    ((name, args),) = routed
    assert args[4:6] == (4, 7)


@pytest.mark.parametrize("status", ["ARCHIVED", "ERROR", "RETRY"])
def test_a_job_in_another_status_is_left_alone(
    mongo_db: Any, routed: list, status: str
) -> None:
    _dispatch(mongo_db, status)
    assert routed == []


def test_read_grades_on_an_archived_job_is_ignored(mongo_db: Any, routed: list) -> None:
    _dispatch(
        mongo_db,
        "ARCHIVED",
        {"job_id": "job", "read_grades": True, "question_index": 1},
    )
    assert routed == []


def test_an_unknown_job_is_refused(mongo_db: Any, routed: list) -> None:
    with pytest.raises(KeyError, match="not found"):
        dispatch.process(
            Database(),
            MagicMock(),
            Storage(),
            MagicMock(),
            {"job_id": "nope"},
            Path("/tmp"),
        )
    assert routed == []


def test_a_dispatched_job_is_kept_alive_while_it_runs(
    mongo_db: Any, routed: list
) -> None:
    _dispatch(mongo_db, "QUEUED")
    assert mongo_db["eval_jobs"].find_one({"job_id": "job"})["alive_time"] is not None


# ------------------------------------------------------- copies from a zip


def _zip_copies(
    storage_root: Path,
    pdf_factory: Callable[..., Path],
    tmp_path: Path,
    pages_by_name: dict[str, int],
) -> None:
    zip_path = storage_root / "zips" / "job" / "upload.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as z:
        for name, n_pages in pages_by_name.items():
            z.write(pdf_factory(tmp_path / f"{name}.pdf", n_pages), f"{name}.pdf")


def _split_job(mongo_db: Any, status: str = "SPLIT") -> dict:
    job = {
        "job_id": "job",
        "user_id": "teacher",
        "job_status": status,
        "n_pages_per_question": [["Q1", 2], ["Q2", 0]],
    }
    mongo_db["eval_jobs"].insert_one(dict(job))
    return job


def test_a_split_job_gets_its_copies_and_is_queued_for_recognition(
    tmp_path: Path, storage_root: Path, mongo_db: Any, pdf_factory: Callable[..., Path]
) -> None:
    job = _split_job(mongo_db)
    _zip_copies(storage_root, pdf_factory, tmp_path, {"alice": 3, "bob": 3})
    redis, sio = fakeredis.FakeStrictRedis(), MagicMock()

    create_job(Database(), redis, Storage(), sio, job, tmp_path / "work")

    docs = sorted(
        d["filename"] for d in mongo_db["job_documents"].find({"job_id": "job"})
    )
    assert docs == ["alice", "bob"]
    assert (
        mongo_db["job_questions"].count_documents({"job_id": "job", "question": "Q1"})
        == 2
    )
    assert mongo_db["eval_jobs"].find_one({"job_id": "job"})["job_status"] == "QUEUED"
    assert _statuses(sio) == ["QUEUED"]
    assert _queue(redis) == [{"job_id": "job"}]


def test_a_split_job_with_a_bad_copy_waits_for_a_retry(
    tmp_path: Path, storage_root: Path, mongo_db: Any, pdf_factory: Callable[..., Path]
) -> None:
    job = _split_job(mongo_db)
    _zip_copies(storage_root, pdf_factory, tmp_path, {"alice": 3, "short": 2})
    redis, sio = fakeredis.FakeStrictRedis(), MagicMock()

    create_job(Database(), redis, Storage(), sio, job, tmp_path / "work")

    record = mongo_db["eval_jobs"].find_one({"job_id": "job"})
    assert record["job_status"] == "RETRY"
    assert "short.pdf a 1 page manquante" in record["copies_errors"]
    assert record["job_infos"] == record["copies_errors"]
    assert _queue(redis) == []
    # the good copy is kept
    assert mongo_db["job_documents"].count_documents({"filename": "alice"}) == 1


def test_a_split_job_that_crashes_is_set_in_error(
    tmp_path: Path, mongo_db: Any
) -> None:
    job = {"job_id": "job", "user_id": "teacher", "job_status": "SPLIT"}
    mongo_db["eval_jobs"].insert_one(dict(job))  # no n_pages_per_question
    sio = MagicMock()

    create_job(Database(), fakeredis.FakeStrictRedis(), Storage(), sio, job, tmp_path)

    assert mongo_db["eval_jobs"].find_one({"job_id": "job"})["job_status"] == "ERROR"
    assert _statuses(sio) == ["ERROR"]


def test_added_copies_with_errors_still_queue_the_good_ones(
    tmp_path: Path, storage_root: Path, mongo_db: Any, pdf_factory: Callable[..., Path]
) -> None:
    job = _split_job(mongo_db, status="VALIDATION")
    _zip_copies(storage_root, pdf_factory, tmp_path, {"carol": 3, "long": 5})
    redis, sio = fakeredis.FakeStrictRedis(), MagicMock()

    add_copies_to_job(Database(), redis, Storage(), sio, job, tmp_path / "work")

    record = mongo_db["eval_jobs"].find_one({"job_id": "job"})
    assert record["job_status"] == "QUEUED"
    assert "long.pdf a 2 pages de trop" in record["copies_errors"]
    assert _queue(redis) == [{"job_id": "job"}]
    assert mongo_db["job_documents"].count_documents({"filename": "carol"}) == 1


def test_copies_added_to_a_deleted_job_are_removed_again(
    tmp_path: Path,
    storage_root: Path,
    mongo_db: Any,
    pdf_factory: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _split_job(mongo_db, status="VALIDATION")
    _zip_copies(storage_root, pdf_factory, tmp_path, {"carol": 3})
    import tasks.copies as copies

    # the job is deleted by the teacher while its copies are being split
    real_insert = copies.insert_copies

    def insert_then_delete(*args: Any) -> None:
        real_insert(*args)
        mongo_db["eval_jobs"].delete_many({"job_id": "job"})

    monkeypatch.setattr(copies, "insert_copies", insert_then_delete)
    redis = fakeredis.FakeStrictRedis()

    add_copies_to_job(Database(), redis, Storage(), MagicMock(), job, tmp_path / "work")

    assert mongo_db["job_documents"].count_documents({"job_id": "job"}) == 0
    assert mongo_db["job_questions"].count_documents({"job_id": "job"}) == 0
    assert not (storage_root / "documents" / "job").exists()
    assert _queue(redis) == []


# ------------------------------------------------------------- read grades


def _question_to_read(storage_root: Path, mongo_db: Any, fixture: dict) -> int:
    target = storage_root / "documents" / "job" / "Q3"
    target.mkdir(parents=True)
    shutil.copy(FIXTURES / "ink_grades" / fixture["file"], target / fixture["file"])
    mongo_db["eval_jobs"].insert_one(
        {
            "job_id": "job",
            "user_id": "teacher",
            "job_status": "VALIDATION",
            "n_max_points_per_question": [["Q3", fixture["max_points"]]],
            "bonus_enabled_map": [["Q3", False]],
        }
    )
    mongo_db["job_questions"].insert_one(
        {
            "job_id": "job",
            "document_index": 5,
            "question_index": 3,
            "question": "Q3",
            "rel_filepath": f"documents/job/Q3/{fixture['file']}",
            "status": Document_Status.TO_VALIDATE.value,
            "grade": None,
        }
    )
    return Database().bump_auto_grade_run("job", 3)


def test_read_grades_reads_the_question_and_reports_each_copy(
    tmp_path: Path, storage_root: Path, mongo_db: Any
) -> None:
    spec = json.loads((FIXTURES / "ink_grades" / "expected.json").read_text())[
        "fixtures"
    ]
    fixture = next(f for f in spec if f["file"] == "ink_circled_single.pdf")
    run = _question_to_read(storage_root, mongo_db, fixture)
    sio = MagicMock()

    dispatch.process(
        Database(),
        MagicMock(),
        Storage(),
        sio,
        {"job_id": "job", "read_grades": True, "question_index": "3", "run": run},
        tmp_path,
    )

    stored = mongo_db["job_questions"].find_one({"document_index": 5})
    assert stored["auto_grade"] == fixture["expected"]
    assert stored["grade"] is None  # the teacher's field is not touched
    events = [(c.args[0], json.loads(c.args[1])) for c in sio.emit.call_args_list]
    progress = [e for name, e in events if name == "job_status"]
    assert progress[0]["job_infos"] == "Lecture des notes de Q3 : 0/1 (0 %)"
    assert progress[-1]["job_infos"] == "Lecture des notes de Q3 : 1/1 (100 %)"
    assert all(e["status"] == "VALIDATION" for e in progress)
    ready = [e for name, e in events if name == "document_ready"]
    assert (
        ready[0]["document_index"] == 5
        and ready[0]["auto_grade"] == fixture["expected"]
    )
    assert ready[0]["question_index"] == 3
    # the last event closes the pass: no document_index, the screen refetches
    assert ready[-1] == {"job_id": "job", "user_id": "teacher", "questions": True}
    assert (
        mongo_db["eval_jobs"].find_one({"job_id": "job"})["job_status"] == "VALIDATION"
    )


def test_read_grades_of_a_superseded_run_emits_nothing(
    tmp_path: Path, storage_root: Path, mongo_db: Any
) -> None:
    spec = json.loads((FIXTURES / "ink_grades" / "expected.json").read_text())[
        "fixtures"
    ]
    run = _question_to_read(storage_root, mongo_db, spec[0])
    sio = MagicMock()

    dispatch.process(
        Database(),
        MagicMock(),
        Storage(),
        sio,
        {"job_id": "job", "read_grades": True, "question_index": 3, "run": run - 1},
        tmp_path,
    )

    assert not sio.emit.called
    assert "auto_grade" not in mongo_db["job_questions"].find_one({"document_index": 5})


def test_read_grades_without_a_question_does_nothing(
    tmp_path: Path, mongo_db: Any
) -> None:
    from tasks.read_grades import read_grades_for_job

    sio = MagicMock()
    read_grades_for_job(
        Database(),
        Storage(),
        sio,
        {"job_id": "job", "user_id": "u", "job_status": "RUN"},
        None,
        None,
        MagicMock(),
    )
    assert not sio.emit.called


# ---------------------------------------------------------------- deletion


def test_delete_job_removes_the_storage_and_every_record(
    storage_root: Path, mongo_db: Any, pdf_factory: Callable[..., Path]
) -> None:
    for folder in ("documents", "cover_pages", "corrected_copies", "zips"):
        pdf_factory(storage_root / folder / "job" / "a.pdf")
    for name in (
        "job_documents",
        "job_questions",
        "eval_jobs",
        "jobs_output",
        "versions",
    ):
        mongo_db[name].insert_many([{"job_id": "job"}, {"job_id": "other"}])

    cleanup.delete_job(Database(), Storage(), "job")

    for folder in ("documents", "cover_pages", "corrected_copies", "zips"):
        assert not (storage_root / folder / "job").exists(), folder
    for name in (
        "job_documents",
        "job_questions",
        "eval_jobs",
        "jobs_output",
        "versions",
    ):
        assert [d["job_id"] for d in mongo_db[name].find()] == ["other"], name


def test_delete_job_survives_a_storage_failure(mongo_db: Any) -> None:
    storage = MagicMock()
    storage.remove_job.side_effect = OSError("NFS down")
    mongo_db["eval_jobs"].insert_one({"job_id": "job"})

    cleanup.delete_job(Database(), storage, "job")

    assert mongo_db["eval_jobs"].count_documents({}) == 0


# --------------------------------------------------------------- templates


def _template_png(storage_root: Path, crops: list[tuple[str, list[float]]]) -> str:
    import cv2
    import numpy as np

    page = np.full((3300, 2550), 255, np.uint8)
    for crop_file, box in crops:
        crop = cv2.imread(
            str(FIXTURES / "recognition" / crop_file), cv2.IMREAD_GRAYSCALE
        )
        x1, y1 = int(box[0] * 2550), int(box[2] * 3300)
        x2, y2 = x1 + crop.shape[1], y1 + crop.shape[0]
        page[y1:y2, x1:x2] = crop
    path = storage_root / "templates" / "front.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(page, cv2.COLOR_GRAY2BGR))
    return "templates/front.png"


def test_a_template_without_boxes_is_rendered_as_is(
    tmp_path: Path, storage_root: Path, mongo_db: Any
) -> None:
    file_id = _template_png(storage_root, [])
    mongo_db["template"].insert_one(
        {"template_id": "front", "user_id": "teacher", "template_file_id": file_id}
    )
    sio = MagicMock()

    templates.process_template(Database(), Storage(), sio, "front", tmp_path)

    record = mongo_db["template"].find_one({"template_id": "front"})
    assert record["template_rendered_file_id"] == "templates/front-rendered.png"
    assert (storage_root / "templates" / "front-rendered.png").is_file()
    event, payload = sio.emit.call_args.args
    assert event == "template_rendered"
    assert json.loads(payload)["template_id"] == "front"


def test_a_template_grade_box_is_counted_in_questions(
    tmp_path: Path, storage_root: Path, mongo_db: Any
) -> None:
    grade_box = RECOGNITION["grade_box"]
    file_id = _template_png(storage_root, [("grades_blank.png", grade_box)])
    mongo_db["template"].insert_one(
        {
            "template_id": "front",
            "user_id": "teacher",
            "template_file_id": file_id,
            "grade_box": grade_box,
        }
    )

    templates.process_template(Database(), Storage(), MagicMock(), "front", tmp_path)

    # six boxes: five questions and the total
    assert mongo_db["template"].find_one({"template_id": "front"})["n_questions"] == 5


def test_an_unknown_template_is_refused(tmp_path: Path, mongo_db: Any) -> None:
    with pytest.raises(KeyError, match="not found"):
        templates.process_template(Database(), Storage(), MagicMock(), "nope", tmp_path)


# -------------------------------------------------------------- queue loop


@pytest.fixture
def executor_main(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list]:
    """Run job_executor as __main__ for two turns of its non-blocking loop."""
    redis = fakeredis.FakeStrictRedis()
    sio = MagicMock()
    calls = []
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("REDIS_POP", raising=False)
    monkeypatch.setattr(clients, "redis_client", lambda: redis)
    monkeypatch.setattr(clients, "socketio_client", lambda: sio)

    def recorder(name: str, fail: bool = False) -> Callable[..., None]:
        def record(*args: Any) -> None:
            # the work dir exists while the task runs, and only then
            calls.append(
                (name, args, Path(args[-1]).is_dir() if name != "delete" else None)
            )
            if fail:
                raise RuntimeError("task failed")

        return record

    monkeypatch.setattr(dispatch, "process", recorder("process", fail=True))
    monkeypatch.setattr(templates, "process_template", recorder("template"))
    monkeypatch.setattr(cleanup, "delete_job", recorder("delete"))

    def run(*payloads: dict | str) -> list:
        for payload in payloads:
            redis.rpush(
                "job_queue",
                payload if isinstance(payload, str) else json.dumps(payload),
            )
        runpy.run_path(str(EXECUTOR / "job_executor.py"), run_name="__main__")
        return calls

    run.redis, run.sio = redis, sio
    return run


def test_the_executor_refuses_an_invalid_job_id_and_renders_templates(
    executor_main: Callable[..., list],
) -> None:
    calls = executor_main({"job_id": "../etc"}, {"template_id": "tpl-1"})

    assert [(name, args[3]) for name, args, _ in calls] == [("template", "tpl-1")]
    assert calls[0][2] is True
    assert not (EXECUTOR / "tmp_tpl-1").exists()
    assert executor_main.redis.llen("job_queue") == 0
    assert executor_main.sio.disconnect.called


def test_the_executor_deletes_and_survives_a_failing_task(
    executor_main: Callable[..., list],
) -> None:
    calls = executor_main({"job_id": "gone", "delete": True}, {"job_id": "job-1"})

    assert [
        (name, args[4] if name == "process" else args[2]) for name, args, _ in calls
    ] == [
        ("delete", "gone"),
        ("process", {"job_id": "job-1"}),
    ]
    # the task raised, its work dir is removed all the same
    assert calls[1][2] is True
    assert not (EXECUTOR / "tmp_job-1").exists()
    assert not (EXECUTOR / "tmp_gone").exists()


def test_the_executor_stops_on_an_empty_queue(
    executor_main: Callable[..., list],
) -> None:
    assert executor_main() == []
