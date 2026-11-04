"""Several class lists for a task: one Moodle export per assignment.

On creation and when the lists are replaced, a student found in two exports
is answered with a 409 naming them, until the teacher says which export they
belong to. The task keeps one csv with the export of each student; the
outputs of a finished task are downloaded per export.
"""

import csv
import io
import json
import uuid

import pytest

from rmn_common.class_lists import LIST_COLUMN

SECTION_A = (
    b"Identifiant,Nom complet,Matricule,Note\nP1,Alice A,0123456,\nP2,Bob B,2345678,\n"
)
SECTION_B = (
    b"Identifiant,Nom complet,Matricule,Groupe,Note\n"
    b"P7,Carl C,3456789,02,\nP8,Bob B,2345678,02,\n"
)
SECTION_C = b"Identifiant,Nom complet,Matricule,Note\nP9,Dana D,4567890,\n"


def _files(*named):
    return [(io.BytesIO(content), name) for name, content in named]


def _rows(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _evaluate(client, token, csvs, **extra):
    data = {
        "token": token,
        "front_template_id": "front",
        "regular_template_id": "regular",
        "front_template_name": "front",
        "regular_template_name": "regular",
        "job_name": "exam",
        "statistics_for_students": "true",
        "n_pages_per_question": json.dumps([["Q1", 1]]),
        "n_max_points_per_question": json.dumps([["Q1", 5]]),
        "bonus_enabled_map": json.dumps([["Q1", False]]),
        "notes_csv_file": csvs,
        "zip_file": (io.BytesIO(b"PK\x05\x06" + b"\x00" * 18), "copies.zip"),
        **extra,
    }
    return client.post("/jobs/evaluate", data=data, content_type="multipart/form-data")


@pytest.fixture
def alice(user_factory, login):
    user_factory("alice")
    return login("alice")


@pytest.fixture
def jobs(app_module_fixture):
    return app_module_fixture.mongo["RMN"]["eval_jobs"]


# ------------------------------------------------------------- on creation ---
def test_a_task_of_two_lists_keeps_one_csv_with_the_list_of_each_student(
    client, alice, jobs, storage_root
):
    resp = _evaluate(
        client,
        alice,
        _files(("Section A.csv", SECTION_A), ("Section C.csv", SECTION_C)),
    )

    assert resp.status_code == 200, resp.data
    job = jobs.find_one({"user_id": "alice"})
    assert job["class_lists"] == [
        {
            "name": "Section A",
            "columns": ["Identifiant", "Nom complet", "Matricule", "Note"],
        },
        {
            "name": "Section C",
            "columns": ["Identifiant", "Nom complet", "Matricule", "Note"],
        },
    ]
    rows = _rows(storage_root / job["notes_file_id"])
    assert [(r["Matricule"], r[LIST_COLUMN]) for r in rows] == [
        ("0123456", "Section A"),
        ("2345678", "Section A"),
        ("4567890", "Section C"),
    ]


def test_a_student_in_two_lists_is_asked_about_before_anything_is_created(
    client, alice, jobs
):
    resp = _evaluate(client, alice, _files(("A.csv", SECTION_A), ("B.csv", SECTION_B)))

    assert resp.status_code == 409
    body = resp.get_json(force=True)
    assert body["duplicates"] == [
        {"matricule": "2345678", "name": "Bob B", "lists": ["A", "B"]}
    ]
    assert body["lists"] == ["A", "B"]
    assert jobs.count_documents({}) == 0


def test_the_student_goes_to_the_list_chosen_only(client, alice, jobs, storage_root):
    resp = _evaluate(
        client,
        alice,
        _files(("A.csv", SECTION_A), ("B.csv", SECTION_B)),
        assignments=json.dumps({"2345678": "B"}),
    )

    assert resp.status_code == 200, resp.data
    job = jobs.find_one({"user_id": "alice"})
    rows = _rows(storage_root / job["notes_file_id"])
    assert [(r["Matricule"], r[LIST_COLUMN]) for r in rows] == [
        ("0123456", "A"),
        ("3456789", "B"),
        ("2345678", "B"),
    ]


@pytest.mark.parametrize("assignments", ["{", "[]", json.dumps({"2345678": 2})])
def test_malformed_assignments_are_refused(client, alice, jobs, assignments):
    resp = _evaluate(
        client,
        alice,
        _files(("A.csv", SECTION_A), ("B.csv", SECTION_B)),
        assignments=assignments,
    )
    assert resp.status_code == 400
    assert jobs.count_documents({}) == 0


def test_a_list_without_matricules_is_refused(client, alice, jobs):
    resp = _evaluate(
        client, alice, _files(("A.csv", SECTION_A), ("B.csv", b"Nom,Note\nX,\n"))
    )
    assert resp.status_code == 400
    assert "Matricule" in resp.get_json(force=True)["response"]
    assert jobs.count_documents({}) == 0


def test_a_single_list_is_stored_as_it_always_was(client, alice, jobs, storage_root):
    resp = _evaluate(client, alice, _files(("A.csv", SECTION_A)))
    assert resp.status_code == 200, resp.data
    job = jobs.find_one({"user_id": "alice"})
    assert "class_lists" not in job
    assert LIST_COLUMN not in (storage_root / job["notes_file_id"]).read_text()


def test_a_task_made_from_one_of_several_lists_keeps_them(
    client, alice, jobs, storage_root
):
    _evaluate(client, alice, _files(("A.csv", SECTION_A), ("C.csv", SECTION_C)))
    source = jobs.find_one({"user_id": "alice"})
    data = {
        "token": alice,
        "front_template_id": "front",
        "regular_template_id": "regular",
        "front_template_name": "front",
        "regular_template_name": "regular",
        "job_name": "bis",
        "statistics_for_students": "true",
        "n_pages_per_question": json.dumps([["Q1", 1]]),
        "n_max_points_per_question": json.dumps([["Q1", 5]]),
        "bonus_enabled_map": json.dumps([["Q1", False]]),
        "source_job_id": source["job_id"],
        "zip_file": (io.BytesIO(b"PK\x05\x06" + b"\x00" * 18), "copies.zip"),
    }
    resp = client.post("/jobs/evaluate", data=data, content_type="multipart/form-data")

    assert resp.status_code == 200, resp.data
    copy = jobs.find_one({"job_name": "bis"})
    assert copy["class_lists"] == source["class_lists"]
    assert LIST_COLUMN in (storage_root / copy["notes_file_id"]).read_text()


# ------------------------------------------------------ replacing the lists ---
@pytest.fixture
def two_lists(client, alice, jobs, storage_root):
    # storage_root first: it empties the tree the task writes to
    resp = _evaluate(client, alice, _files(("A.csv", SECTION_A), ("C.csv", SECTION_C)))
    assert resp.status_code == 200, resp.data
    return jobs.find_one({"user_id": "alice"})


def _update(client, token, job_id, keep, csvs=(), **extra):
    data = {"job_id": job_id, "token": token, "keep": json.dumps(keep), **extra}
    if csvs:
        data["csv"] = list(csvs)
    return client.post(
        "/jobs/update/csv", data=data, content_type="multipart/form-data"
    )


def test_a_list_is_removed_and_another_added(
    client, alice, jobs, two_lists, storage_root
):
    job_id = two_lists["job_id"]
    resp = _update(client, alice, job_id, ["C"], _files(("B.csv", SECTION_B)))

    assert resp.status_code == 200, resp.data
    job = jobs.find_one({"job_id": job_id})
    assert [entry["name"] for entry in job["class_lists"]] == ["C", "B"]
    assert job["class_lists"][1]["columns"] == [
        "Identifiant",
        "Nom complet",
        "Matricule",
        "Groupe",
        "Note",
    ]
    assert job["students_list"] == [
        {"matricule": "4567890", "Nom complet": "Dana D"},
        {"matricule": "3456789", "Nom complet": "Carl C"},
        {"matricule": "2345678", "Nom complet": "Bob B"},
    ]
    # the csv the processing starts from and the one it wrote, both
    for file_id in (job["notes_file_id"], f"output_csv/{job_id}.csv"):
        rows = _rows(storage_root / file_id)
        assert [(r["Matricule"], r[LIST_COLUMN]) for r in rows] == [
            ("4567890", "C"),
            ("3456789", "B"),
            ("2345678", "B"),
        ]


def test_an_added_list_with_a_student_already_there_is_asked_about(
    client, alice, jobs, two_lists
):
    job_id = two_lists["job_id"]
    resp = _update(client, alice, job_id, ["A", "C"], _files(("B.csv", SECTION_B)))
    assert resp.status_code == 409
    assert resp.get_json(force=True)["duplicates"][0]["lists"] == ["A", "B"]
    assert jobs.find_one({"job_id": job_id})["class_lists"] == two_lists["class_lists"]

    resp = _update(
        client,
        alice,
        job_id,
        ["A", "C"],
        _files(("B.csv", SECTION_B)),
        assignments=json.dumps({"2345678": "A"}),
    )
    assert resp.status_code == 200, resp.data
    students = jobs.find_one({"job_id": job_id})["students_list"]
    assert [s["matricule"] for s in students] == [
        "0123456",
        "2345678",
        "4567890",
        "3456789",
    ]


def test_the_lists_cannot_all_be_removed_nor_an_unknown_one_kept(
    client, alice, two_lists
):
    job_id = two_lists["job_id"]
    assert _update(client, alice, job_id, []).status_code == 400
    resp = _update(client, alice, job_id, ["Z"])
    assert resp.status_code == 400
    assert "Z" in resp.get_json(force=True)["response"]
    assert _update(client, alice, job_id, "A").status_code == 400  # not a list


def test_the_list_of_a_task_given_one_is_named_notes(client, alice, jobs, storage_root):
    _evaluate(client, alice, _files(("A.csv", SECTION_A)))
    job = jobs.find_one({"user_id": "alice"})
    info = client.post("/jobs/info", data={"job_id": job["job_id"], "token": alice})
    assert info.get_json(force=True)["response"]["class_lists"] == ["notes"]

    resp = _update(
        client, alice, job["job_id"], ["notes"], _files(("C.csv", SECTION_C))
    )

    assert resp.status_code == 200, resp.data
    job = jobs.find_one({"job_id": job["job_id"]})
    assert [entry["name"] for entry in job["class_lists"]] == ["notes", "C"]
    info = client.post("/jobs/info", data={"job_id": job["job_id"], "token": alice})
    assert info.get_json(force=True)["response"]["class_lists"] == ["notes", "C"]


def test_another_user_cannot_replace_the_lists(client, two_lists, user_factory, login):
    user_factory("mallory")
    resp = _update(client, login("mallory"), two_lists["job_id"], ["A"])
    assert resp.status_code == 404


# -------------------------------------------------------------- the outputs ---
@pytest.fixture
def finished_two_lists(user_factory, job_factory, app_module_fixture, storage_root):
    user_factory("alice")
    job_id = f"lists-{uuid.uuid4().hex[:8]}"
    job_factory(job_id, "alice", status="ARCHIVED", statistics_for_students=False)
    for rel, content in (
        (f"output_csv/{job_id}.csv", b"all"),
        (f"output_csv/{job_id}_1.csv", b"notes of A"),
        (f"output_csv/{job_id}_2.csv", b"notes of B"),
    ):
        path = storage_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    app_module_fixture.mongo["RMN"]["jobs_output"].insert_one(
        {
            "job_id": job_id,
            "user_id": "alice",
            "notes_csv_file_id": f"output_csv/{job_id}.csv",
            "zip_id_list": ["all.zip", "a1.zip", "b1.zip", "b2.zip"],
            "class_lists": [
                {
                    "name": "A",
                    "notes_csv_file_id": f"output_csv/{job_id}_1.csv",
                    "zip_indices": [1],
                },
                {
                    "name": "B",
                    "notes_csv_file_id": f"output_csv/{job_id}_2.csv",
                    "zip_indices": [2, 3],
                },
            ],
        }
    )
    return job_id


def test_the_files_of_each_list_are_listed(client, login, finished_two_lists):
    resp = client.post(
        "/jobs/batch/info", data={"job_id": finished_two_lists, "token": login("alice")}
    )
    assert resp.get_json(force=True) == {
        "nZips": 4,
        "stats": False,
        "lists": [{"name": "A", "zips": [1]}, {"name": "B", "zips": [2, 3]}],
    }


def test_the_notes_of_each_list_are_downloaded(client, login, finished_two_lists):
    token = login("alice")

    def notes(**extra):
        return client.post(
            "/files/download",
            data={
                "job_id": finished_two_lists,
                "token": token,
                "file": "notes_csv_file",
                **extra,
            },
        )

    assert notes().data == b"all"
    assert notes(list_index="1").data == b"notes of B"
    assert notes(list_index="2").status_code == 404
    assert notes(list_index="x").status_code == 400


def test_a_shared_link_names_the_list(client, login, finished_two_lists):
    resp = client.post(
        "/files/share",
        data={
            "job_id": finished_two_lists,
            "token": login("alice"),
            "file": "notes_csv_file",
            "list_index": "1",
        },
        headers={"Host": "localhost"},
    )
    assert resp.status_code == 200, resp.data
    assert resp.get_json(force=True)["response"]["share_url"].endswith("&list_index=1")
