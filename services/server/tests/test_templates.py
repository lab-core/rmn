"""Template listing, details, edition and deletion (no pdf rendering involved)."""

import json
import os

import pytest

import service.template_service as template_service


def _template(mongo, template_id, user_id, name, locked=False, **extra):
    doc = {
        "template_id": template_id,
        "user_id": user_id,
        "template_name": name,
        "template_file_id": f"templates/{template_id}.pdf",
        "n_questions": 3,
        "locked": locked,
    }
    doc.update(extra)
    mongo["RMN"]["template"].insert_one(doc)
    return doc


def _auth(token, user="alice", **extra):
    return {"user_id": user, "token": token, **extra}


@pytest.fixture
def alice(client, user_factory, login):
    user_factory("alice")
    return login("alice")


def test_listing_merges_own_and_default_templates(client, alice, app_module_fixture):
    mongo = app_module_fixture.mongo
    _template(mongo, "t1", "alice", "Mine")
    _template(mongo, "t2", "bob", "Bobs")
    _template(mongo, "d1", "root", "Example: Exam", locked=True, src="/srv/default/exam.tex")

    resp = client.post("/user/template", data=_auth(alice))

    assert resp.status_code == 200
    templates = resp.get_json(force=True)["response"]
    assert [(t["template_name"], t["locked"]) for t in templates] == [("Example: Exam", True), ("Mine", False)]
    assert templates[0]["src_name"] == "exam.tex"
    assert templates[1]["n_questions"] == 3 and "src_name" not in templates[1]


def test_own_copy_of_a_default_template_is_shown_unlocked(client, alice, app_module_fixture):
    mongo = app_module_fixture.mongo
    _template(mongo, "d1", "root", "Example: Exam", locked=True, src="/srv/default/exam.tex")
    _template(mongo, "t1", "alice", "Example: Exam")
    templates = client.post("/user/template", data=_auth(alice)).get_json(force=True)["response"]
    assert len(templates) == 1
    assert templates[0]["template_id"] == "t1" and templates[0]["locked"] is False
    assert templates[0]["src_name"] == "exam.tex"


def test_template_info_converts_boxes_and_lock(client, alice, app_module_fixture):
    mongo = app_module_fixture.mongo
    _template(mongo, "t1", "alice", "Mine", grade_box=[0.1, 0.9, 0.6, 0.9], matricule_box=None)
    _template(mongo, "d1", "root", "Default", locked=True)
    _template(mongo, "l1", "alice", "My locked", locked=True)

    info = client.post("/template/info", data=_auth(alice, template_id="t1")).get_json(force=True)["response"]
    assert info["grade_box"] == pytest.approx({"x1": 10.0, "x2": 90.0, "y1": 60.0, "y2": 90.0})
    assert info["matricule_box"] is None
    assert info["n_questions"] == 3
    assert not info["locked"]

    info = client.post("/template/info", data=_auth(alice, template_id="d1")).get_json(force=True)["response"]
    assert info["locked"] is True
    info = client.post("/template/info", data=_auth(alice, template_id="l1")).get_json(force=True)["response"]
    assert not info["locked"]  # locked, but mine

    assert client.post("/template/info", data=_auth(alice, template_id="nope")).status_code == 400
    assert client.post("/template/info", data=_auth(alice)).status_code == 400


def test_modify_updates_name_and_boxes_and_requeues_the_render(client, alice, app_module_fixture):
    mongo = app_module_fixture.mongo
    _template(mongo, "t1", "alice", "Mine")

    resp = client.post(
        "/template/modify",
        data=_auth(
            alice,
            template_id="t1",
            template_name="Renamed",
            grade_box=json.dumps({"x1": 10, "x2": 90, "y1": 60, "y2": 90}),
            matricule_box=json.dumps({"x1": None, "x2": None, "y1": None, "y2": None}),
        ),
    )

    assert resp.status_code == 200
    template = mongo["RMN"]["template"].find_one({"template_id": "t1"})
    assert template["template_name"] == "Renamed"
    assert template["grade_box"] == pytest.approx([0.1, 0.9, 0.6, 0.9])
    assert template["matricule_box"] is None
    # the service keeps its own Redis connection (the executor renders the template)
    queue = [json.loads(p) for p in template_service.redis.lrange("job_queue", 0, -1)]
    assert queue == [{"template_id": "t1"}]

    assert client.post("/template/modify", data=_auth(alice, template_id="t1")).status_code == 400


def test_modify_cannot_touch_another_users_template(client, alice, app_module_fixture):
    mongo = app_module_fixture.mongo
    _template(mongo, "t2", "bob", "Bobs")
    client.post("/template/modify", data=_auth(alice, template_id="t2", template_name="Hijacked"))
    assert mongo["RMN"]["template"].find_one({"template_id": "t2"})["template_name"] == "Bobs"


def test_delete_removes_the_files_and_the_record(client, alice, app_module_fixture):
    mongo = app_module_fixture.mongo
    storage = app_module_fixture.storage
    _template(mongo, "t1", "alice", "Mine", template_rendered_file_id="templates/t1.png")
    for rel in ("templates/t1.pdf", "templates/t1.png", "templates/t2.pdf"):
        path = storage.abs_path(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()

    resp = client.post("/template/delete", data=_auth(alice, template_id="t1"))

    assert resp.status_code == 200
    assert mongo["RMN"]["template"].find_one({"template_id": "t1"}) is None
    assert not os.path.exists(storage.abs_path("templates/t1.pdf"))
    assert not os.path.exists(storage.abs_path("templates/t1.png"))
    assert os.path.exists(storage.abs_path("templates/t2.pdf"))
    os.remove(storage.abs_path("templates/t2.pdf"))

    assert client.post("/template/delete", data=_auth(alice, template_id="t1")).status_code == 400
    assert client.post("/template/delete", data=_auth(alice)).status_code == 400
