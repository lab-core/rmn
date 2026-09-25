"""Creating templates from a pdf, downloading them, and the default templates.

The page the teacher picked is rendered to a png in the storage, the record
points at it, and a template with boxes is queued for the executor to render
the boxes on. The pdfs are built in the test: two blank pages of different
sizes, so the rendered png tells which page was kept.
"""

import io
import json
import os
import shutil
import warnings

import pytest
from PIL import Image
from pypdf import PdfWriter

import default_templates.config as default_config
import service.template_service as template_service

ADMIN = {"X-Admin-Key": "test-admin-key"}


def _pdf(*sizes):
    writer = PdfWriter()
    for width, height in sizes:
        writer.add_blank_page(width=width, height=height)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _queue():
    return [json.loads(p) for p in template_service.redis.lrange("job_queue", 0, -1)]


def _listing(folder):
    return set(os.listdir(folder)) if os.path.isdir(folder) else set()


@pytest.fixture(autouse=True)
def _drop_uploaded_pdfs():
    """Safety net: remove what a failing test left in the service's temp folder."""
    folder = template_service.TEMP_FOLDER
    before = _listing(folder)
    yield
    for name in _listing(folder) - before:
        os.remove(folder / name)


@pytest.fixture(autouse=True)
def _empty_template_queue():
    """The service's own Redis connection is not flushed between tests."""
    yield
    template_service.redis.delete("job_queue")


@pytest.fixture
def alice(user_factory, login):
    user_factory("alice")
    return login("alice")


@pytest.fixture
def cleanup(app_module_fixture):
    """Remove the stored files a test created (the storage root outlives it)."""
    created = []
    yield created
    for rel in created:
        try:
            os.remove(app_module_fixture.storage.abs_path(rel))
        except OSError:
            pass


def _upload(client, token, pdf, **fields):
    return client.post(
        "/templates",
        data={
            "user_id": "alice",
            "token": token,
            "template_file": (io.BytesIO(pdf), "exam.pdf"),
            **fields,
        },
        content_type="multipart/form-data",
    )


def test_upload_renders_the_chosen_page_and_queues_the_boxes(
    client, alice, app_module_fixture, cleanup
):
    queued = len(_queue())
    resp = _upload(
        client,
        alice,
        _pdf((72, 72), (144, 72)),
        template_name="Final",
        template_page="1",
        grade_box=json.dumps({"x1": 10, "x2": 90, "y1": 60, "y2": 90}),
        matricule_box=json.dumps({"x1": 5, "x2": 50, "y1": 10, "y2": 20}),
    )

    assert resp.status_code == 200, resp.data
    body = resp.get_json(force=True)["response"]
    assert body["template_name"] == "Final"
    stored = app_module_fixture.mongo["RMN"]["template"].find_one(
        {"template_id": body["template_id"]}
    )
    cleanup.append(stored["template_file_id"])
    assert stored["user_id"] == "alice" and stored["locked"] is False
    assert stored["template_file_id"] == f"template/{body['template_id']}.png"
    assert stored["grade_box"] == pytest.approx([0.1, 0.9, 0.6, 0.9])
    assert stored["matricule_box"] == pytest.approx([0.05, 0.5, 0.1, 0.2])
    # page 1 (2 x 1 inches) at 300 dpi, not page 0
    png = app_module_fixture.storage.abs_path(stored["template_file_id"])
    with Image.open(png) as img:
        assert img.size == (600, 300)
    assert _queue()[queued:] == [{"template_id": body["template_id"]}]


def test_upload_leaves_nothing_in_the_temp_folder(client, alice, cleanup):
    folder = template_service.TEMP_FOLDER
    before = _listing(folder)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        resp = _upload(client, alice, _pdf((72, 72)))

    assert resp.status_code == 200, resp.data
    template_id = resp.get_json(force=True)["response"]["template_id"]
    cleanup.append(f"template/{template_id}.png")
    # the uploaded pdf used to stay there, and the file the
    # upload was saved through was never closed
    assert _listing(folder) == before
    assert not [w for w in caught if issubclass(w.category, ResourceWarning)]


def test_upload_without_boxes_is_not_queued(client, alice, app_module_fixture, cleanup):
    queued = len(_queue())
    resp = _upload(client, alice, _pdf((72, 72)))

    assert resp.status_code == 200, resp.data
    template_id = resp.get_json(force=True)["response"]["template_id"]
    stored = app_module_fixture.mongo["RMN"]["template"].find_one(
        {"template_id": template_id}
    )
    cleanup.append(stored["template_file_id"])
    assert stored["template_name"] == ""
    assert "grade_box" not in stored and "matricule_box" not in stored
    assert len(_queue()) == queued


@pytest.mark.parametrize(
    "pdf,fields",
    [(b"not a pdf", {}), (_pdf((72, 72)), {"template_page": "3"})],
    ids=["garbage", "page-out-of-range"],
)
def test_an_unreadable_upload_stores_nothing(
    client, alice, app_module_fixture, pdf, fields
):
    storage = app_module_fixture.storage
    before = _listing(storage.abs_path("template"))
    folder = template_service.TEMP_FOLDER
    temp_before = _listing(folder)

    resp = _upload(client, alice, pdf, **fields)

    assert resp.status_code == 500
    assert app_module_fixture.mongo["RMN"]["template"].count_documents({}) == 0
    assert _listing(storage.abs_path("template")) == before
    assert _listing(folder) == temp_before


def test_upload_requires_the_template_file(client, alice):
    resp = client.post("/templates", data={"user_id": "alice", "token": alice})
    assert resp.status_code == 400
    resp = client.post(
        "/templates",
        data={"user_id": "alice", "token": alice, "other": (io.BytesIO(b"x"), "x.pdf")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_upload_requires_the_user_id(client, alice, app_module_fixture):
    resp = client.post(
        "/templates",
        data={"token": alice, "template_file": (io.BytesIO(_pdf((72, 72))), "e.pdf")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert app_module_fixture.mongo["RMN"]["template"].count_documents({}) == 0


def test_upload_needs_a_login(client, user_factory):
    user_factory("alice")
    resp = _upload(client, "forged", _pdf((72, 72)))
    assert resp.status_code == 401


# ---------------------------------------------------------------- reading ---
def test_download_prefers_the_rendered_file(client, alice, app_module_fixture, cleanup):
    storage = app_module_fixture.storage
    for rel, content in (("template/r1.png", b"RAW"), ("template/r1_r.png", b"BOXES")):
        path = storage.abs_path(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        cleanup.append(rel)
    app_module_fixture.mongo["RMN"]["template"].insert_one(
        {
            "template_id": "r1",
            "user_id": "alice",
            "template_name": "Mine",
            "template_file_id": "template/r1.png",
            "template_rendered_file_id": "template/r1_r.png",
            "locked": False,
        }
    )

    resp = client.post(
        "/templates/download",
        data={"user_id": "alice", "token": alice, "template_id": "r1"},
    )

    assert resp.status_code == 200
    assert resp.data == b"BOXES"
    assert client.post("/templates/download", data={"token": alice}).status_code == 400


def test_the_source_of_a_default_template_can_be_downloaded(
    client, alice, app_module_fixture, tmp_path
):
    src = tmp_path / "exam.tex"
    src.write_bytes(b"\\documentclass{article}")
    templates = app_module_fixture.mongo["RMN"]["template"]
    templates.insert_one(
        {
            "template_id": "d1",
            "user_id": "admin",
            "template_name": "Example",
            "template_file_id": "template/d1.png",
            "locked": True,
            "src": str(src),
        }
    )
    templates.insert_one(
        {
            "template_id": "t1",
            "user_id": "alice",
            "template_name": "Mine",
            "template_file_id": "template/t1.png",
            "locked": False,
        }
    )

    resp = client.post(
        "/templates/download/src", data={"token": alice, "template_id": "d1"}
    )
    assert resp.status_code == 200
    assert resp.data == b"\\documentclass{article}"
    resp.close()

    # a template uploaded as a pdf has no source
    resp = client.post(
        "/templates/download/src", data={"token": alice, "template_id": "t1"}
    )
    assert resp.status_code == 400
    assert (
        client.post("/templates/download/src", data={"token": alice}).status_code == 400
    )


def test_listing_and_info_require_the_user_id(client, alice):
    assert client.post("/templates/user", data={"token": alice}).status_code == 400
    resp = client.post("/templates/info", data={"token": alice, "template_id": "t1"})
    assert resp.status_code == 400


# ------------------------------------------------------ default templates ---
@pytest.fixture
def defaults(tmp_path, monkeypatch):
    """The default templates pointed at copies: creating one rewrites its pdf."""
    shipped = os.path.dirname(default_config.__file__)
    copies = {}
    for name, template in default_config.default_templates.items():
        pdf = template["src"].rsplit(".", 1)[0] + ".pdf"
        folder = tmp_path / os.path.basename(os.path.dirname(pdf))
        folder.mkdir(exist_ok=True)
        shutil.copy(pdf, folder)
        copies[name] = {
            **template,
            "src": str(folder / os.path.basename(template["src"])),
        }
        assert pdf.startswith(shipped)
    monkeypatch.setattr(default_config, "default_templates", copies)
    return copies


def test_admin_installs_the_default_templates_locked(
    client, app_module_fixture, defaults, cleanup
):
    templates = app_module_fixture.mongo["RMN"]["template"]

    resp = client.post("/admin/template", data={"user_id": "admin"}, headers=ADMIN)

    assert resp.status_code == 200, resp.data
    added = resp.get_json(force=True)["response"]
    stored = {t["template_name"]: t for t in templates.find()}
    cleanup.extend(t["template_file_id"] for t in stored.values())
    assert sorted(stored) == sorted(f"Example: {n}" for n in defaults)
    assert {a["template_id"] for a in added} == {
        t["template_id"] for t in stored.values()
    }
    for name, template in defaults.items():
        row = stored[f"Example: {name}"]
        assert row["locked"] is True and row["src"] == template["src"]
        assert row.get("matricule_box") == template.get("matricule_box")
        assert os.path.isfile(
            app_module_fixture.storage.abs_path(row["template_file_id"])
        )

    # installing again replaces them instead of adding a second copy
    first_ids = {t["template_file_id"] for t in stored.values()}
    resp = client.post("/admin/template", data={"user_id": "admin"}, headers=ADMIN)
    assert resp.status_code == 200
    again = list(templates.find())
    cleanup.extend(t["template_file_id"] for t in again)
    assert len(again) == len(defaults)
    for rel in first_ids:
        assert not os.path.exists(app_module_fixture.storage.abs_path(rel))


def test_default_templates_need_the_admin_key(client, app_module_fixture, defaults):
    resp = client.post("/admin/template", data={"user_id": "admin"})
    assert resp.status_code == 403
    assert app_module_fixture.mongo["RMN"]["template"].count_documents({}) == 0


def test_a_broken_default_template_stops_the_install(
    client, app_module_fixture, defaults, monkeypatch
):
    name = next(iter(defaults))
    broken = {**defaults, name: {**defaults[name], "src": "/nonexistent/x.tex"}}
    monkeypatch.setattr(default_config, "default_templates", broken)
    resp = client.post("/admin/template", data={"user_id": "admin"}, headers=ADMIN)
    assert resp.status_code == 500
    assert app_module_fixture.mongo["RMN"]["template"].count_documents({}) == 0


def test_deleting_a_user_removes_the_rendered_template_files(
    client, user_factory, app_module_fixture
):
    user_factory("carol")
    storage = app_module_fixture.storage
    for rel in ("template/c1.png", "template/c1_r.png"):
        path = storage.abs_path(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").close()
    app_module_fixture.mongo["RMN"]["template"].insert_one(
        {
            "template_id": "c1",
            "user_id": "carol",
            "template_name": "Mine",
            "template_file_id": "template/c1.png",
            "template_rendered_file_id": "template/c1_r.png",
            "locked": False,
        }
    )

    resp = client.post("/admin/delete/user", data={"username": "carol"}, headers=ADMIN)

    assert resp.status_code == 200, resp.data
    assert app_module_fixture.mongo["RMN"]["template"].count_documents({}) == 0
    assert not os.path.exists(storage.abs_path("template/c1.png"))
    assert not os.path.exists(storage.abs_path("template/c1_r.png"))
