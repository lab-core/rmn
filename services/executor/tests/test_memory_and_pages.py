"""The MAX_RAM_GB guard measures the container; whole-document rasterisation is capped."""

from process_copy import recognize


def test_memory_is_read_from_the_cgroup_when_available(tmp_path):
    current = tmp_path / "memory.current"
    current.write_text("2500000000\n")
    assert recognize.memory_used_gb([str(tmp_path / "missing"), str(current)]) == 2.5


def test_memory_falls_back_to_this_process(tmp_path):
    # no cgroup file (a laptop): the process' resident size, never the node's
    used = recognize.memory_used_gb([str(tmp_path / "missing")])
    assert 0 < used < 64


def test_full_document_rasterisation_is_capped(monkeypatch, tmp_path):
    calls = []

    def fake_convert(fpdf, dpi, **kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(recognize, "convert_from_path", fake_convert)
    monkeypatch.setattr(recognize, "MAX_RASTERISED_PAGES", 7)
    assert recognize.gray_images(str(tmp_path / "x.pdf")) == []
    assert calls == [{"first_page": 1, "last_page": 7}]
