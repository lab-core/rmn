"""The pages of a copy, rendered when they are read."""

import pytest
from process_copy import pages as pages_module
from process_copy.pages import GrayPages


@pytest.fixture
def renders(monkeypatch: pytest.MonkeyPatch) -> list:
    """Record the pages pdftoppm is asked for."""
    asked = []
    convert = pages_module.convert_from_path

    def recording(fpdf, **kwargs):
        asked.append((kwargs["first_page"], kwargs["last_page"]))
        return convert(fpdf, **kwargs)

    monkeypatch.setattr(pages_module, "convert_from_path", recording)
    return asked


def test_a_page_is_rendered_once_and_only_when_read(tmp_path, pdf_factory, renders):
    pdf = pdf_factory(tmp_path / "booklet.pdf", n_pages=16)
    grays = GrayPages(str(pdf), dpi=30, straighten=False)
    assert len(grays) == 16 and renders == []

    first = grays[0]
    assert grays[0] is first
    grays[3]
    assert renders == [(1, 1), (4, 4)]
    assert grays.rendered() == 2
    assert first.ndim == 2  # gray


def test_the_pages_stop_at_the_end_of_the_copy_and_at_the_cap(
    tmp_path, pdf_factory, monkeypatch, renders
):
    pdf = pdf_factory(tmp_path / "copy.pdf", n_pages=3)
    grays = GrayPages(str(pdf), dpi=30, straighten=False)
    assert len(list(grays)) == 3
    with pytest.raises(IndexError):
        grays[3]

    monkeypatch.setattr(pages_module, "MAX_RASTERISED_PAGES", 2)
    assert len(GrayPages(str(pdf), dpi=30, straighten=False)) == 2
