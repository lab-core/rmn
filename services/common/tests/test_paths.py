"""csv values used as file names."""

import pytest

from rmn_common.paths import ensure_within, safe_path_component


def test_safe_path_component_keeps_names_readable_but_inside_the_folder():
    assert safe_path_component("Émilie Dupont-Tremblay") == "Émilie Dupont-Tremblay"
    assert safe_path_component("../../mnt/storage/csv") == ".._.._mnt_storage_csv"
    assert safe_path_component("A/B") == "A_B"
    assert safe_path_component("..") == "_"
    assert safe_path_component("   ") == "_"
    assert safe_path_component(3.0) == "3.0"


def test_ensure_within_accepts_children_and_rejects_escapes(tmp_path):
    assert (
        ensure_within(tmp_path / "a" / "b", tmp_path)
        == (tmp_path / "a" / "b").resolve()
    )
    assert ensure_within(tmp_path, tmp_path) == tmp_path.resolve()
    with pytest.raises(ValueError):
        ensure_within(tmp_path / ".." / "elsewhere", tmp_path)
