"""``/front_page``: a LaTeX cover page prepended to every copy of a Moodle zip.

pdflatex is replaced by a small script (the server image has none): it turns
``data.tex`` into a one-page PDF and fails for a student called "Broken".
"""

import io
import os
import sys
import textwrap
import zipfile

import pymupdf
import pytest

from service.front_page_service import FrontPageHandler

FAKE_PDFLATEX = textwrap.dedent(
    """\
    #!{python}
    import pathlib, sys
    import pymupdf
    data = pathlib.Path("data.tex").read_text()
    if "Broken" in data:
        sys.exit(1)
    doc = pymupdf.Document()
    doc.new_page().insert_text((72, 72), data)
    doc.save(pathlib.Path(sys.argv[-1]).stem + ".pdf")
    """
)


@pytest.fixture
def fake_pdflatex(tmp_path, monkeypatch):
    script = tmp_path / "pdflatex"
    script.write_text(FAKE_PDFLATEX.format(python=sys.executable))
    script.chmod(0o755)
    monkeypatch.setattr(FrontPageHandler, "CMD", str(script))
    return script


@pytest.fixture
def temp_root(tmp_path, monkeypatch, app_module_fixture):
    root = tmp_path / "front_page_temp"
    monkeypatch.setattr(app_module_fixture, "FRONT_PAGE_TEMP_FOLDER", root)
    return root


def _pdf_bytes():
    doc = pymupdf.Document()
    doc.new_page()
    return doc.tobytes()


def _moodle_zip(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i, name in enumerate(names):
            zf.writestr(
                f"{name}_{i + 10}_{1000000 + i}_assignsubmission_file_/copy.pdf",
                _pdf_bytes(),
            )
    buf.seek(0)
    return buf


def _post(client, token, names, suffix="S"):
    return client.post(
        "/front_page",
        data={
            "user_id": "alice",
            "token": token,
            "suffix": suffix,
            "moodle_zip": (_moodle_zip(names), "moodle.zip"),
            "latex_front_page": (io.BytesIO(b"\\input{data}"), "front.tex"),
        },
        content_type="multipart/form-data",
    )


@pytest.fixture
def token(user_factory, login):
    user_factory("alice")
    return login("alice")


def test_without_pdflatex_the_endpoint_says_so(client, token, temp_root, monkeypatch):
    # it used to answer 200 with an empty zip after deleting every input
    monkeypatch.setattr(FrontPageHandler, "CMD", "pdflatex-not-installed-here")
    resp = _post(client, token, ["Alice Martin"])
    assert resp.status_code == 501
    assert "pdflatex" in resp.get_json(force=True)["response"]


def test_every_copy_gets_a_front_page(client, token, temp_root, fake_pdflatex):
    resp = _post(client, token, ["Alice Martin", "Bob Roy"])
    assert resp.status_code == 200, resp.data
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        assert sorted(zf.namelist()) == [
            "Alice_Martin_1000000_S.pdf",
            "Bob_Roy_1000001_S.pdf",
        ]
        copy = pymupdf.Document(stream=zf.read("Alice_Martin_1000000_S.pdf"))
    assert copy.page_count == 2  # front page + the copy
    assert "Alice Martin" in copy[0].get_text()
    # nothing left behind, and no directory named after the user
    assert os.listdir(temp_root) == []


def test_a_failed_front_page_is_reported_not_hidden(
    client, token, temp_root, fake_pdflatex
):
    resp = _post(client, token, ["Alice Martin", "Broken Student"])
    assert resp.status_code == 500
    assert (
        resp.get_json(force=True)["response"]
        == "Error: 1 copie(s) sans page couverture, 1 réussie(s)."
    )
    assert os.listdir(temp_root) == []


def test_zip_inflating_past_the_budget_is_refused(
    client, token, temp_root, fake_pdflatex, monkeypatch, app_module_fixture
):
    monkeypatch.setattr(app_module_fixture, "FRONT_PAGE_MAX_UNZIPPED_BYTES", 100)
    resp = _post(client, token, ["Alice Martin"])
    assert resp.status_code == 413
    assert os.listdir(temp_root) == []


def test_names_are_escaped_for_tex(tmp_path, fake_pdflatex):
    handler = FrontPageHandler()
    (tmp_path / "front.tex").write_text("\\input{data}")
    pdf = handler.create_front_page(
        str(tmp_path / "front.tex"),
        str(tmp_path / "data.tex"),
        "O'Neil & Sons }\\input{/etc/passwd}{",
        "12_3",
        str(tmp_path),
    )
    data = (tmp_path / "data.tex").read_text()
    assert "\\&" in data and "\\input{/etc" not in data and "12\\_3" in data
    assert os.path.exists(pdf)
    # the worker's cwd is untouched (os.chdir used to leave it in a deleted directory)
    assert os.getcwd() != str(tmp_path)
