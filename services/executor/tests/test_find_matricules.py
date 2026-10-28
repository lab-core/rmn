"""The matricule pass over a batch of copies, around the recognition itself."""

from unittest.mock import MagicMock

import pytest
from process_copy import matricules
from process_copy.database import Database
from rmn_common.status import Document_Status


@pytest.fixture
def reader(monkeypatch: pytest.MonkeyPatch, mongo_db) -> MagicMock:
    """Stub the classifier, the roster and the socket of ``find_matricules``."""
    sio = MagicMock()
    monkeypatch.setattr(matricules, "socketio_client", lambda: sio)
    monkeypatch.setattr(matricules, "load_classifier", lambda: None)
    monkeypatch.setattr(matricules, "load_csv", lambda grades_csv: ([], []))
    db = Database()
    for i in range(3):
        db.insert_document(
            "job", i, [], "", Document_Status.NOT_READY, "", 0, f"copy{i}"
        )
    return sio


def _read(monkeypatch: pytest.MonkeyPatch, on_read=None) -> None:
    def fake_find_file_matricule(job_id, doc_index, file, db, *args):
        # the real one returns early on a copy that is no longer NOT READY
        if (
            db.get_document(job_id, doc_index)["status"]
            != Document_Status.NOT_READY.value
        ):
            return True, None, None
        if on_read:
            on_read(doc_index)
        return True, f"100000{doc_index}", 0.9

    monkeypatch.setattr(matricules, "find_file_matricule", fake_find_file_matricule)
    matricules.find_matricules(
        ["a.pdf", "b.pdf", "c.pdf"], 0, [], 0, "job", "alice", None, None, {}
    )


def test_a_copy_validated_before_its_turn_is_not_read(reader, monkeypatch, mongo_db):
    docs = mongo_db["job_documents"]
    docs.update_one(
        {"job_id": "job", "document_index": 1},
        {"$set": {"status": Document_Status.VALIDATED.value, "matricule": "2222222"}},
    )
    _read(monkeypatch)

    by_index = {d["document_index"]: d for d in docs.find({"job_id": "job"})}
    assert by_index[1]["matricule"] == "2222222"
    assert by_index[1]["status"] == "VALIDATED"
    assert (
        by_index[0]["matricule"] == "1000000" and by_index[2]["matricule"] == "1000002"
    )
    emitted = [c.args[1] for c in reader.emit.call_args_list]
    assert len(emitted) == 2 and not any('"document_index": 1' in e for e in emitted)


def test_a_copy_validated_while_it_is_read_keeps_the_human_answer(
    reader, monkeypatch, mongo_db
):
    docs = mongo_db["job_documents"]

    def validate_meanwhile(doc_index):
        if doc_index == 1:
            docs.update_one(
                {"job_id": "job", "document_index": 1},
                {
                    "$set": {
                        "status": Document_Status.VALIDATED.value,
                        "matricule": "2222222",
                    }
                },
            )

    _read(monkeypatch, validate_meanwhile)

    doc = docs.find_one({"job_id": "job", "document_index": 1})
    assert (doc["status"], doc["matricule"]) == ("VALIDATED", "2222222")
    assert "matricule_confidence" not in doc
    assert (
        docs.find_one({"job_id": "job", "document_index": 2})["matricule"] == "1000002"
    )
